import logging
import os
from pathlib import Path

import discord
import numpy as np
import torch
from numpy.typing import NDArray
from PIL import Image
from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_BATCH_SIZE
from src.database import search_similar_frames

logger = logging.getLogger(__name__)


def resolve_embedding_device() -> str:
    configured = os.getenv("EMBEDDING_DEVICE", "").strip()
    if configured:
        return configured

    if torch.cuda.is_available():
        return "cuda"

    if torch.backends.mps.is_available():
        return "mps"

    return "cpu"


EMBEDDING_DEVICE = resolve_embedding_device()
model = SentenceTransformer(
    "sentence-transformers/clip-ViT-B-32",
    device=EMBEDDING_DEVICE,
)
logger.info("CLIP model loaded on device: %s", EMBEDDING_DEVICE)


def embed_image(path: Path) -> NDArray[np.float32]:
    return embed_images([path])[0]


def embed_images(paths: list[Path]) -> list[NDArray[np.float32]]:
    if not paths:
        return []

    images = [Image.open(path).convert("RGB") for path in paths]

    embeddings = model.encode(
        images,
        batch_size=EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return [np.asarray(embedding, dtype=np.float32) for embedding in embeddings]


async def search_similar(image: discord.Attachment):
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        image_path = temp_dir / image.filename
        await image.save(image_path)

        embedding = embed_image(image_path)

        results = search_similar_frames(
            embedding,
            limit=25,
        )

        return dedupe_results_by_indexed_precut(results, limit=5)


def dedupe_results_by_indexed_precut(results, limit: int = 5):
    seen_indexed_precut_ids: set[int] = set()
    deduped = []

    for result in results:
        indexed_precut_id = result["indexed_precut_id"]
        if indexed_precut_id in seen_indexed_precut_ids:
            continue

        seen_indexed_precut_ids.add(indexed_precut_id)
        deduped.append(result)

        if len(deduped) >= limit:
            break

    return deduped
