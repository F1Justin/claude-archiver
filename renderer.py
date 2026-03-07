"""
Output generators for JSON and Markdown formats.
"""

import json
import logging
import re
import shutil
from pathlib import Path

from config import JSON_DIR, MD_DIR, MEMORIES_DIR

logger = logging.getLogger(__name__)

MAX_FILENAME_LEN = 80


def write_conversation_json(conv: dict) -> Path:
    """Write a merged conversation to json/{uuid}.json."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    path = JSON_DIR / f"{conv['uuid']}.json"

    output = {k: v for k, v in conv.items() if k != "_source"}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Wrote JSON: %s", path.name)
    return path


def write_conversation_md(conv: dict) -> Path:
    """Write a conversation as a readable Markdown file."""
    MD_DIR.mkdir(parents=True, exist_ok=True)

    filename = build_md_filename(conv)
    path = MD_DIR / filename

    lines = []
    lines.append(f"<!-- uuid: {conv['uuid']} -->")
    lines.append(f"# {conv.get('name', 'Untitled')}\n")

    created = conv.get("created_at", "")[:10]
    updated = conv.get("updated_at", "")[:10]
    msg_count = len(conv.get("chat_messages", []))
    model = conv.get("model", "")
    meta_parts = []
    if created:
        meta_parts.append(f"创建: {created}")
    if updated:
        meta_parts.append(f"更新: {updated}")
    meta_parts.append(f"消息数: {msg_count}")
    if model:
        meta_parts.append(f"模型: {model}")
    lines.append(f"> {' | '.join(meta_parts)}\n")

    if conv.get("summary"):
        lines.append(f"**摘要:** {conv['summary']}\n")

    for msg in conv.get("chat_messages", []):
        sender = msg.get("sender", "unknown")
        role = "Human" if sender == "human" else "Assistant"
        timestamp = _format_timestamp(msg.get("created_at", ""))

        lines.append(f"## {role}")
        if timestamp:
            lines.append(f"*{timestamp}*\n")

        text = get_message_text(msg)
        if text:
            lines.append(text)
        lines.append("")

    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Wrote MD: %s", filename)
    return path


def build_md_filename(conv: dict) -> str:
    """Build a safe filename like '对话标题_2026-03-07.md'."""
    title = conv.get("name", "Untitled")
    created = conv.get("created_at", "")[:10]

    safe_title = sanitize_filename(title)
    if not safe_title:
        safe_title = conv["uuid"][:8]

    if len(safe_title) > MAX_FILENAME_LEN:
        safe_title = safe_title[:MAX_FILENAME_LEN]

    base = f"{safe_title}_{created}" if created else safe_title

    candidate = f"{base}.md"
    existing = MD_DIR / candidate
    if existing.exists():
        existing_uuid = _read_uuid_from_md(existing)
        if existing_uuid and existing_uuid != conv["uuid"]:
            candidate = f"{base}_{conv['uuid'][:8]}.md"

    return candidate


def _read_uuid_from_md(path: Path) -> str | None:
    """Try to read the uuid from an existing md file's metadata comment."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            first_lines = f.read(500)
        match = re.search(r"uuid:\s*([a-f0-9-]+)", first_lines)
        return match.group(1) if match else None
    except OSError:
        return None


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip('. ')
    return name


def get_message_text(msg: dict) -> str:
    """Extract readable text from a message."""
    text = msg.get("text", "")
    if text:
        return text

    content_blocks = msg.get("content", [])
    parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _format_timestamp(ts: str) -> str:
    """Convert '2026-03-07T11:28:32.650019Z' -> '2026-03-07 11:28:32'."""
    if not ts:
        return ""
    ts = ts.replace("T", " ")
    if "." in ts:
        ts = ts[:ts.index(".")]
    ts = ts.rstrip("Z")
    return ts


def write_memories(memories_data, export_date: str) -> Path | None:
    """Write memories to memories/memories_YYYY-MM-DD.json."""
    if not memories_data:
        return None

    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"memories_{export_date}.json"
    path = MEMORIES_DIR / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(memories_data, f, ensure_ascii=False, indent=2)

    logger.info("Wrote memories: %s", filename)
    return path


def cleanup_stale_md(conv: dict):
    """Remove old md files for a conversation if the title changed."""
    uuid = conv["uuid"]
    current_filename = build_md_filename(conv)

    for md_file in MD_DIR.glob("*.md"):
        if md_file.name == current_filename:
            continue
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                header = f.read(500)
            if uuid in header:
                logger.info("Removing stale MD: %s (replaced by %s)", md_file.name, current_filename)
                md_file.unlink()
        except OSError:
            pass
