import logging
import subprocess
import tempfile
from pathlib import Path

from scenedetect import ContentDetector, detect
from tqdm import tqdm

from src.database import add_frame_embedding, add_precut, add_scene
from src.embedding import embed_image
from src.precut import download_precut_from_url

logger = logging.getLogger(__name__)


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
) -> None:
    logger.debug(
        "Generating preview at %.2fs -> %s",
        seconds,
        output_path,
    )

    subprocess.run(
        [
            "ffmpeg",
            "-ss",
            str(seconds),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_previews(
    video_path: Path,
    scenes: dict[int, tuple[float, float]],
    previews_dir: Path,
) -> dict[int, list[Path]]:
    logger.debug(
        "Generating previews for %d scenes",
        len(scenes),
    )

    previews: dict[int, list[Path]] = {}

    for scene_index, (start, end) in scenes.items():
        scene_dir = previews_dir / str(scene_index)

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

        scene_previews: list[Path] = []

        for preview_index, timestamp in enumerate(preview_times):
            output_path = scene_dir / f"{preview_index}.jpg"

            generate_preview(
                video_path,
                timestamp,
                output_path,
            )

            scene_previews.append(output_path)

        previews[scene_index] = scene_previews

    logger.debug(
        "Generated %d preview images",
        sum(len(paths) for paths in previews.values()),
    )

    return previews


async def process_precuts(precuts) -> None:
    total_precuts = len(precuts)

    logger.info(
        "Starting processing for %d precuts",
        total_precuts,
    )

    processed = 0
    failed = 0

    progress = tqdm(
        precuts,
        total=total_precuts,
        desc="Processing precuts",
        unit="precut",
    )

    for precut in progress:
        precut_id = precut["id"]

        progress.set_postfix(
            processed=processed,
            failed=failed,
            current=precut_id,
        )

        logger.info(
            "Processing precut %s (%d/%d)",
            precut_id,
            processed + failed + 1,
            total_precuts,
        )

        try:
            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)

                logger.debug(
                    "Created temporary directory for precut %s: %s",
                    precut_id,
                    temp_dir,
                )

                logger.info(
                    "[%s] Downloading precut",
                    precut_id,
                )

                download_path = await download_precut_from_url(
                    precut["attachment_url"],
                    temp_dir,
                )

                logger.info(
                    "[%s] Download complete: %s",
                    precut_id,
                    download_path,
                )

                logger.info(
                    "[%s] Converting to 24fps",
                    precut_id,
                )

                converted_path = make_precut_24fps(download_path)

                logger.info(
                    "[%s] Detecting scenes",
                    precut_id,
                )

                scenes = detect_scenes(converted_path)

                logger.info(
                    "[%s] Detected %d scenes",
                    precut_id,
                    len(scenes),
                )

                logger.info(
                    "[%s] Generating previews",
                    precut_id,
                )

                previews = make_previews(
                    converted_path,
                    scenes,
                    temp_dir / "previews",
                )

                preview_count = sum(len(paths) for paths in previews.values())

                logger.info(
                    "[%s] Generated %d previews",
                    precut_id,
                    preview_count,
                )

                logger.info(
                    "[%s] Saving precut to database",
                    precut_id,
                )

                add_precut(
                    id=precut["id"],
                    message_id=precut["message_id"],
                    channel_id=precut["channel_id"],
                    user_id=precut["user_id"],
                    created_at=precut["created_at"],
                )

                logger.info(
                    "[%s] Saving %d scenes to database",
                    precut_id,
                    len(scenes),
                )

                scene_ids: dict[int, int] = {}

                for scene_index, (start_time, end_time) in scenes.items():
                    scene_id = add_scene(
                        precut_id=precut_id,
                        scene_index=scene_index,
                        start_time=start_time,
                        end_time=end_time,
                    )

                    scene_ids[scene_index] = scene_id

                logger.info(
                    "[%s] Creating %d embeddings",
                    precut_id,
                    preview_count,
                )

                for scene_index, preview_paths in previews.items():
                    scene_id = scene_ids[scene_index]

                    for preview_index, preview_path in enumerate(preview_paths):
                        logger.debug(
                            "[%s] Embedding scene %d preview %d",
                            precut_id,
                            scene_index,
                            preview_index,
                        )

                        embedding = embed_image(preview_path)

                        add_frame_embedding(
                            scene_id=scene_id,
                            embedding=embedding,
                        )

                logger.info(
                    "[%s] Saved %d embeddings",
                    precut_id,
                    preview_count,
                )

            processed += 1

            logger.info(
                "[%s] Finished successfully",
                precut_id,
            )

        except Exception:
            failed += 1

            logger.exception(
                "[%s] Failed to process precut",
                precut_id,
            )

        progress.set_postfix(
            processed=processed,
            failed=failed,
        )

    logger.info(
        "Finished processing precuts. Processed: %d, Failed: %d, Total: %d",
        processed,
        failed,
        total_precuts,
    )
