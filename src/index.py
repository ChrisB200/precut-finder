import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from scenedetect import ContentDetector, detect
from tqdm import tqdm

from src.config import PREVIEWS_DIR
from src.database import (
    add_frame_embedding,
    add_precut_post,
    add_scene,
    get_indexed_precut_by_hash,
    get_or_create_indexed_precut,
    indexed_precut_has_scenes,
    precut_post_exists,
)
from src.embedding import embed_image
from src.precut import download_precut_from_url

logger = logging.getLogger(__name__)


def parse_created_at(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(value)


def make_precut_24fps(path: Path) -> Path:
    output_path = path.with_name(f"{path.stem}_24fps.mp4")

    logger.debug(
        "Converting %s to 24fps -> %s",
        path,
        output_path,
    )

    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(path),
            "-vf",
            "fps=24",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-y",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    logger.debug("Finished 24fps conversion: %s", output_path)

    return output_path


def detect_scenes(path: Path) -> dict[int, tuple[float, float]]:
    logger.debug("Detecting scenes in %s", path)

    detected_scenes = detect(
        str(path),
        ContentDetector(threshold=27.0),
    )

    scenes: dict[int, tuple[float, float]] = {}

    for scene_index, (start, end) in enumerate(detected_scenes):
        scenes[scene_index] = (
            start.get_seconds(),
            end.get_seconds(),
        )

    logger.debug(
        "Detected %d scenes in %s",
        len(scenes),
        path,
    )

    return scenes


def generate_preview(
    video_path: Path,
    seconds: float,
    output_path: Path,
    scale_height: int | None = None,
) -> None:
    logger.debug(
        "Generating preview at %.2fs -> %s",
        seconds,
        output_path,
    )

    command = [
        "ffmpeg",
        "-ss",
        str(seconds),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
    ]

    if scale_height is not None:
        command.extend(
            [
                "-vf",
                f"scale=-2:{scale_height}",
            ]
        )

    command.extend(
        [
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ]
    )

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_previews(
    video_path: Path,
    scenes: dict[int, tuple[float, float]],
    temp_previews_dir: Path,
    persistent_previews_dir: Path,
) -> tuple[dict[int, list[Path]], dict[int, Path]]:
    logger.debug(
        "Generating previews for %d scenes",
        len(scenes),
    )

    persistent_previews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    previews: dict[int, list[Path]] = {}
    preview_paths: dict[int, Path] = {}

    for scene_index, (start, end) in scenes.items():
        scene_dir = temp_previews_dir / str(scene_index)

        scene_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        duration = end - start

        preview_times = [
            start + duration * 0.25,
            start + duration * 0.50,
            start + duration * 0.75,
        ]

        start_preview_path = scene_dir / "0.jpg"
        middle_preview_path = persistent_previews_dir / f"{scene_index}.jpg"
        end_preview_path = scene_dir / "2.jpg"

        generate_preview(
            video_path,
            preview_times[0],
            start_preview_path,
        )

        generate_preview(
            video_path,
            preview_times[1],
            middle_preview_path,
            scale_height=480,
        )

        generate_preview(
            video_path,
            preview_times[2],
            end_preview_path,
        )

        previews[scene_index] = [
            start_preview_path,
            middle_preview_path,
            end_preview_path,
        ]
        preview_paths[scene_index] = middle_preview_path

    logger.debug(
        "Generated %d preview images",
        sum(len(paths) for paths in previews.values()),
    )

    return previews, preview_paths


async def link_precut_post(precut: dict, indexed_precut_id: int) -> bool:
    return add_precut_post(
        attachment_id=precut["id"],
        indexed_precut_id=indexed_precut_id,
        message_id=precut["message_id"],
        channel_id=precut["channel_id"],
        user_id=precut["user_id"],
        created_at=parse_created_at(precut["created_at"]),
    )


async def process_precuts(precuts) -> None:
    total_precuts = len(precuts)

    logger.info(
        "Starting processing for %d precuts",
        total_precuts,
    )

    processed = 0
    skipped = 0
    failed = 0

    progress = tqdm(
        precuts,
        total=total_precuts,
        desc="Processing precuts",
        unit="precut",
    )

    for precut in progress:
        attachment_id = precut["id"]

        progress.set_postfix(
            processed=processed,
            skipped=skipped,
            failed=failed,
            current=attachment_id,
        )

        if precut_post_exists(attachment_id):
            logger.info(
                "[%s] Skipping already known attachment",
                attachment_id,
            )
            skipped += 1
            continue

        logger.info(
            "Processing precut %s (%d/%d)",
            attachment_id,
            processed + skipped + failed + 1,
            total_precuts,
        )

        try:
            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)

                logger.info(
                    "[%s] Downloading precut",
                    attachment_id,
                )

                download_path, content_hash = await download_precut_from_url(
                    precut["attachment_url"],
                    temp_dir,
                )

                existing = get_indexed_precut_by_hash(content_hash)
                if existing is not None:
                    await link_precut_post(precut, existing["id"])
                    logger.info(
                        "[%s] Linked to existing indexed precut %d (hash %s)",
                        attachment_id,
                        existing["id"],
                        content_hash[:12],
                    )
                    skipped += 1
                    continue

                indexed_precut_id = get_or_create_indexed_precut(content_hash)

                if indexed_precut_has_scenes(indexed_precut_id):
                    await link_precut_post(precut, indexed_precut_id)
                    logger.info(
                        "[%s] Linked to indexed precut %d after concurrent indexing",
                        attachment_id,
                        indexed_precut_id,
                    )
                    skipped += 1
                    continue

                logger.info(
                    "[%s] Download complete: %s (hash %s)",
                    attachment_id,
                    download_path,
                    content_hash[:12],
                )

                logger.info(
                    "[%s] Converting to 24fps",
                    attachment_id,
                )

                converted_path = make_precut_24fps(download_path)

                logger.info(
                    "[%s] Detecting scenes",
                    attachment_id,
                )

                scenes = detect_scenes(converted_path)

                if indexed_precut_has_scenes(indexed_precut_id):
                    await link_precut_post(precut, indexed_precut_id)
                    logger.info(
                        "[%s] Linked to indexed precut %d after concurrent indexing",
                        attachment_id,
                        indexed_precut_id,
                    )
                    skipped += 1
                    continue

                logger.info(
                    "[%s] Detected %d scenes",
                    attachment_id,
                    len(scenes),
                )

                logger.info(
                    "[%s] Generating previews",
                    attachment_id,
                )

                previews, scene_preview_paths = make_previews(
                    converted_path,
                    scenes,
                    temp_dir / "previews",
                    PREVIEWS_DIR / content_hash,
                )

                preview_count = sum(len(paths) for paths in previews.values())

                logger.info(
                    "[%s] Saving %d scenes to database",
                    attachment_id,
                    len(scenes),
                )

                scene_ids: dict[int, int] = {}

                for scene_index, (start_time, end_time) in scenes.items():
                    preview_path = scene_preview_paths[scene_index]

                    scene_id = add_scene(
                        indexed_precut_id=indexed_precut_id,
                        scene_index=scene_index,
                        start_time=start_time,
                        end_time=end_time,
                        preview_path=str(preview_path.resolve()),
                    )

                    scene_ids[scene_index] = scene_id

                logger.info(
                    "[%s] Creating %d embeddings",
                    attachment_id,
                    preview_count,
                )

                for scene_index, preview_paths in previews.items():
                    scene_id = scene_ids[scene_index]

                    for preview_index, preview_path in enumerate(preview_paths):
                        logger.debug(
                            "[%s] Embedding scene %d preview %d",
                            attachment_id,
                            scene_index,
                            preview_index,
                        )

                        embedding = embed_image(preview_path)

                        add_frame_embedding(
                            scene_id=scene_id,
                            embedding=embedding,
                        )

                await link_precut_post(precut, indexed_precut_id)

                logger.info(
                    "[%s] Saved %d embeddings",
                    attachment_id,
                    preview_count,
                )

            processed += 1

            logger.info(
                "[%s] Finished successfully",
                attachment_id,
            )

        except Exception:
            failed += 1

            logger.exception(
                "[%s] Failed to process precut",
                attachment_id,
            )

        progress.set_postfix(
            processed=processed,
            skipped=skipped,
            failed=failed,
        )

    logger.info(
        "Finished processing precuts. Processed: %d, Skipped: %d, Failed: %d, Total: %d",
        processed,
        skipped,
        failed,
        total_precuts,
    )
