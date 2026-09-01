import logging
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scenedetect import ContentDetector, detect
from tqdm import tqdm

from src.config import PREVIEWS_DIR
from src.database import (
    SceneIndexRecord,
    indexed_precut_is_fully_indexed,
    prepare_indexed_precut,
    precut_post_exists,
    save_indexed_precut,
)
from src.embedding import embed_images
from src.precut import download_precut_from_url, filter_pending_precuts

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProcessingStats:
    total: int
    already_indexed: int
    remaining: int
    newly_indexed: int
    linked: int
    failed: int


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
    from src.database import add_precut_post

    return add_precut_post(
        attachment_id=precut["id"],
        indexed_precut_id=indexed_precut_id,
        message_id=precut["message_id"],
        channel_id=precut["channel_id"],
        user_id=precut["user_id"],
        created_at=parse_created_at(precut["created_at"]),
    )


async def process_precuts(
    precuts,
    *,
    channel_name: str | None = None,
) -> ProcessingStats:
    pending = filter_pending_precuts(precuts)
    total = len(precuts)
    already_indexed = total - len(pending)
    remaining = len(pending)

    context = f" in #{channel_name}" if channel_name else ""
    logger.info(
        "Starting sync%s: %d total, %d indexed, %d remaining",
        context,
        total,
        already_indexed,
        remaining,
    )

    stats = ProcessingStats(
        total=total,
        already_indexed=already_indexed,
        remaining=remaining,
        newly_indexed=0,
        linked=0,
        failed=0,
    )

    if not pending:
        logger.info("Nothing left to index%s", context)
        return stats

    desc = f"Indexing #{channel_name}" if channel_name else "Indexing precuts"
    progress = tqdm(
        pending,
        total=remaining,
        desc=desc,
        unit="precut",
        bar_format=(
            "{desc}: {percentage:3.0f}%|{bar}| "
            "{n_fmt}/{total_fmt} "
            "[{elapsed}<{remaining}, {rate_fmt}] {postfix}"
        ),
    )

    for precut in progress:
        attachment_id = precut["id"]
        current_phase = "starting"

        def update_progress() -> None:
            completed = stats.newly_indexed + stats.linked + stats.failed
            left = remaining - completed
            progress.set_postfix(
                left=left,
                new=stats.newly_indexed,
                linked=stats.linked,
                failed=stats.failed,
                phase=current_phase,
                refresh=False,
            )

        update_progress()

        if precut_post_exists(attachment_id):
            stats.linked += 1
            continue

        try:
            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)

                current_phase = "download"
                update_progress()

                download_path, content_hash = await download_precut_from_url(
                    precut["attachment_url"],
                    temp_dir,
                )

                indexed_precut_id, is_complete = prepare_indexed_precut(content_hash)

                if is_complete:
                    current_phase = "link"
                    update_progress()
                    await link_precut_post(precut, indexed_precut_id)
                    stats.linked += 1
                    logger.info(
                        "[%s] Linked to existing indexed precut %d (hash %s)",
                        attachment_id,
                        indexed_precut_id,
                        content_hash[:12],
                    )
                    continue

                current_phase = "convert"
                update_progress()
                converted_path = make_precut_24fps(download_path)

                current_phase = "scenes"
                update_progress()
                scenes = detect_scenes(converted_path)

                if indexed_precut_is_fully_indexed(indexed_precut_id):
                    current_phase = "link"
                    update_progress()
                    await link_precut_post(precut, indexed_precut_id)
                    stats.linked += 1
                    continue

                current_phase = "previews"
                update_progress()
                previews, _scene_preview_paths = make_previews(
                    converted_path,
                    scenes,
                    temp_dir / "previews",
                    PREVIEWS_DIR / content_hash,
                )

                current_phase = "save"
                update_progress()

                preview_paths_ordered: list[Path] = []
                for scene_index in sorted(previews.keys()):
                    preview_paths_ordered.extend(previews[scene_index])

                current_phase = "embed"
                update_progress()
                all_embeddings = embed_images(preview_paths_ordered)

                embedding_offset = 0
                scene_records: list[SceneIndexRecord] = []

                for scene_index in sorted(previews.keys()):
                    preview_paths = previews[scene_index]
                    scene_count = len(preview_paths)
                    scene_embeddings = all_embeddings[
                        embedding_offset : embedding_offset + scene_count
                    ]
                    embedding_offset += scene_count

                    start_time, end_time = scenes[scene_index]
                    scene_records.append(
                        SceneIndexRecord(
                            scene_index=scene_index,
                            start_time=start_time,
                            end_time=end_time,
                            preview_path=f"{content_hash}/{scene_index}.jpg",
                            embeddings=scene_embeddings,
                        )
                    )

                current_phase = "save"
                update_progress()
                save_indexed_precut(
                    indexed_precut_id=indexed_precut_id,
                    scenes=scene_records,
                    attachment_id=precut["id"],
                    message_id=precut["message_id"],
                    channel_id=precut["channel_id"],
                    user_id=precut["user_id"],
                    created_at=parse_created_at(precut["created_at"]),
                )
                stats.newly_indexed += 1

                logger.info(
                    "[%s] Indexed successfully (hash %s, %d scenes)",
                    attachment_id,
                    content_hash[:12],
                    len(scenes),
                )

        except Exception:
            stats.failed += 1
            logger.exception(
                "[%s] Failed to process precut",
                attachment_id,
            )

        update_progress()

    logger.info(
        "Finished sync%s: %d total, %d already indexed, %d newly indexed, "
        "%d linked, %d failed, %d remaining",
        context,
        stats.total,
        stats.already_indexed,
        stats.newly_indexed,
        stats.linked,
        stats.failed,
        stats.remaining - stats.newly_indexed - stats.linked - stats.failed,
    )

    return stats
