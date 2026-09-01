import tempfile
from pathlib import Path

import discord
import numpy as np
from numpy.typing import NDArray
from PIL import Image
from sentence_transformers import SentenceTransformer

from src.database import search_similar_frames

model = SentenceTransformer("sentence-transformers/clip-ViT-B-32")


def embed_image(path: Path) -> NDArray[np.float32]:
    image = Image.open(path).convert("RGB")

    embedding = model.encode(
        image,
        normalize_embeddings=True,
    )

    return np.asarray(embedding, dtype=np.float32)


async def search_similar(image: discord.Attachment):
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
