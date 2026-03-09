#!/usr/bin/env python3
"""
Claude Chat Archiver — incremental dedup & merge for Claude exports.

Usage:
    python main.py --scan        # One-time full scan of existing exports
    python main.py --daemon      # Watch ~/Downloads for new exports
    python main.py --scan --daemon  # Scan first, then watch
"""

import argparse
import logging
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from config import FULL_DIR, SINGLE_DIR, DOWNLOADS_DIR, FULL_EXPORT_PATTERN, SINGLE_EXPORT_PATTERN
from merger import count_new_rounds, group_conversations, has_changed, merge_all_conversations
from parser import extract_memories, parse_full_export_dir, parse_single_export
from renderer import cleanup_stale_md, write_conversation_json, write_conversation_md, write_memories
from watcher import ingest_full_export, ingest_single_export, ingest_single_export_md, start_watcher

logger = logging.getLogger(__name__)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def scan_existing():
    """Scan all existing exports in full/ and single/, merge and output."""
    logger.info("=== Starting full scan ===")

    all_conversations = []

    full_dirs = sorted(FULL_DIR.iterdir()) if FULL_DIR.exists() else []
    for d in full_dirs:
        if d.is_dir() and d.name.startswith("data-"):
            convs = parse_full_export_dir(d)
            all_conversations.extend(convs)

            export_date = _extract_date_from_dirname(d.name)
            memories = extract_memories(d)
            if memories and export_date:
                write_memories(memories, export_date)

    single_files = sorted(SINGLE_DIR.glob("Claude_*.json")) if SINGLE_DIR.exists() else []
    for f in single_files:
        conv = parse_single_export(f)
        if conv:
            all_conversations.append(conv)

    if not all_conversations:
        logger.info("No conversations found.")
        return 0, 0

    result = process_conversations(all_conversations)
    logger.info("=== Full scan complete ===")
    return result


def process_conversations(all_conversations: list[dict]) -> tuple[int, int]:
    """Group, merge, and write output for a list of parsed conversations.

    Returns (conversations_written, new_rounds).
    """
    groups = group_conversations(all_conversations)
    merged = merge_all_conversations(groups)

    written = 0
    skipped = 0
    total_new_rounds = 0
    for conv in merged:
        if has_changed(conv["uuid"], conv):
            total_new_rounds += count_new_rounds(conv["uuid"], conv)
            write_conversation_json(conv)
            write_conversation_md(conv)
            cleanup_stale_md(conv)
            written += 1
        else:
            skipped += 1

    logger.info(
        "Processed %d conversations: %d written (%d new rounds), %d unchanged",
        len(merged), written, total_new_rounds, skipped,
    )
    return written, total_new_rounds


def notify(title: str, message: str):
    """Send a macOS notification."""
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            timeout=5, capture_output=True,
        )
    except Exception as e:
        logger.warning("Failed to send notification: %s", e)


def on_new_files(moved_paths: list[Path]):
    """Callback when watcher detects new files — re-scan and merge."""
    names = [p.name for p in moved_paths]
    logger.info("New files detected: %s", names)
    written, new_rounds = scan_existing()
    if written:
        notify("Claude Archiver", f"更新 {written} 条对话，新增 {new_rounds} 轮问答")
    else:
        notify("Claude Archiver", "已处理，无新内容变化")


def scan_downloads_existing():
    """Check Downloads for any Claude exports that haven't been ingested yet."""
    logger.info("Checking Downloads for existing Claude exports...")
    if not DOWNLOADS_DIR.exists():
        return

    for f in sorted(DOWNLOADS_DIR.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        if re.match(FULL_EXPORT_PATTERN, name):
            ingest_full_export(f)
        elif re.match(SINGLE_EXPORT_PATTERN, name):
            ingest_single_export(f)
            md = f.with_suffix(".md")
            if md.exists():
                ingest_single_export_md(md)


def _extract_date_from_dirname(dirname: str) -> str:
    """Extract YYYY-MM-DD from 'data-2026-03-07-08-40-57-batch-0000'."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", dirname)
    return match.group(1) if match else ""


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Claude Chat Archiver")
    parser.add_argument("--scan", action="store_true", help="Scan existing exports and process")
    parser.add_argument("--daemon", action="store_true", help="Watch ~/Downloads for new exports")
    args = parser.parse_args()

    if not args.scan and not args.daemon:
        parser.print_help()
        sys.exit(1)

    scan_downloads_existing()

    if args.scan:
        scan_existing()

    if args.daemon:
        observer = start_watcher(on_new_files)

        def shutdown(signum, frame):
            logger.info("Shutting down...")
            observer.stop()
            observer.join()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        logger.info("Daemon running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            shutdown(None, None)
    else:
        logger.info("Done.")


if __name__ == "__main__":
    main()
