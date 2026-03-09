"""
File system watcher for ~/Downloads.

Detects Claude export files and moves them to the archive,
then triggers the processing pipeline.
"""

import logging
import re
import shutil
import time
import zipfile
from pathlib import Path
from threading import Timer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import (
    DEBOUNCE_SECONDS,
    DOWNLOADS_DIR,
    FULL_DIR,
    FULL_EXPORT_PATTERN,
    SINGLE_DIR,
    SINGLE_EXPORT_MD_PATTERN,
    SINGLE_EXPORT_PATTERN,
)

logger = logging.getLogger(__name__)


class DownloadHandler(FileSystemEventHandler):
    def __init__(self, on_new_files_callback):
        super().__init__()
        self._callback = on_new_files_callback
        self._pending_timers: dict[str, Timer] = {}

    def on_created(self, event):
        if event.is_directory:
            return
        self._debounce(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self._debounce(event.dest_path)

    def _debounce(self, file_path: str):
        """Wait for file to finish writing before processing."""
        if file_path in self._pending_timers:
            self._pending_timers[file_path].cancel()

        timer = Timer(DEBOUNCE_SECONDS, self._process_file, [file_path])
        self._pending_timers[file_path] = timer
        timer.start()

    def _process_file(self, file_path: str):
        self._pending_timers.pop(file_path, None)
        path = Path(file_path)
        if not path.exists():
            return

        name = path.name
        moved_paths = []

        if re.match(FULL_EXPORT_PATTERN, name):
            result = ingest_full_export(path)
            if result:
                moved_paths.append(result)

        elif re.match(SINGLE_EXPORT_PATTERN, name):
            result = ingest_single_export(path)
            if result:
                moved_paths.append(result)
            md_companion = path.with_suffix(".md")
            if md_companion.exists():
                ingest_single_export_md(md_companion)

        elif re.match(SINGLE_EXPORT_MD_PATTERN, name):
            json_companion = path.with_suffix(".json")
            if not json_companion.exists():
                ingest_single_export_md(path)

        if moved_paths:
            self._callback(moved_paths)


def ingest_full_export(zip_path: Path) -> Path | None:
    """Extract a data-*.zip to full/ directory."""
    FULL_DIR.mkdir(parents=True, exist_ok=True)

    dir_name = zip_path.stem
    dest = FULL_DIR / dir_name

    if dest.exists():
        logger.info("Full export already exists: %s", dir_name)
        return dest

    try:
        _wait_for_stable_size(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
        logger.info("Extracted full export: %s -> %s", zip_path.name, dest)
        trash_dir = FULL_DIR / "_imported_zips"
        trash_dir.mkdir(exist_ok=True)
        shutil.move(str(zip_path), str(trash_dir / zip_path.name))
        logger.info("Moved zip to: %s", trash_dir / zip_path.name)
        return dest
    except (zipfile.BadZipFile, OSError) as e:
        logger.error("Failed to extract %s: %s", zip_path.name, e)
        return None


def ingest_single_export(json_path: Path) -> Path | None:
    """Move a Claude_*.json to single/ directory."""
    SINGLE_DIR.mkdir(parents=True, exist_ok=True)
    dest = SINGLE_DIR / json_path.name

    if dest.exists():
        logger.info("Single export already exists: %s", json_path.name)
        return dest

    try:
        _wait_for_stable_size(json_path)
        shutil.move(str(json_path), str(dest))
        logger.info("Moved single export: %s", json_path.name)
        return dest
    except OSError as e:
        logger.error("Failed to move %s: %s", json_path.name, e)
        return None


def ingest_single_export_md(md_path: Path) -> Path | None:
    """Move a companion .md file to single/ directory."""
    SINGLE_DIR.mkdir(parents=True, exist_ok=True)
    dest = SINGLE_DIR / md_path.name
    if dest.exists():
        return dest
    try:
        shutil.move(str(md_path), str(dest))
        logger.info("Moved single export MD: %s", md_path.name)
        return dest
    except OSError as e:
        logger.error("Failed to move MD %s: %s", md_path.name, e)
        return None


def _wait_for_stable_size(path: Path, interval: float = 0.5, checks: int = 3):
    """Wait until file size stops changing (download complete)."""
    prev_size = -1
    stable_count = 0
    while stable_count < checks:
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size == prev_size and size > 0:
            stable_count += 1
        else:
            stable_count = 0
        prev_size = size
        if stable_count < checks:
            time.sleep(interval)


def start_watcher(callback) -> Observer:
    """Start watching ~/Downloads for Claude exports."""
    observer = Observer()
    handler = DownloadHandler(callback)
    observer.schedule(handler, str(DOWNLOADS_DIR), recursive=False)
    observer.start()
    logger.info("Watching %s for Claude exports...", DOWNLOADS_DIR)
    return observer
