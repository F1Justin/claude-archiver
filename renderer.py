"""
Output generators for JSON and Markdown formats.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import JSON_DIR, MD_DIR, MEMORIES_DIR

logger = logging.getLogger(__name__)

MAX_FILENAME_LEN = 80
_UTC8 = timezone(timedelta(hours=8))


def _utc_to_local(ts: str) -> datetime | None:
    """Parse a UTC timestamp string and convert to UTC+8."""
    if not ts:
        return None
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            return dt.astimezone(_UTC8)
        except ValueError:
            continue
    return None


def _local_date(ts: str) -> str:
    """Extract YYYY-MM-DD in UTC+8 from a UTC timestamp."""
    dt = _utc_to_local(ts)
    return dt.strftime("%Y-%m-%d") if dt else ts[:10]


def _local_datetime(ts: str) -> str:
    """Convert UTC timestamp to 'YYYY-MM-DD HH:MM:SS' in UTC+8."""
    dt = _utc_to_local(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _set_file_times(path: Path, created_ts: str, updated_ts: str):
    """Set file creation time and modification time from UTC timestamp strings.

    On macOS/APFS, setting mtime to before current birthtime causes the
    filesystem to pull birthtime back automatically. We exploit this:
      1. Set mtime to created_ts (older) → birthtime snaps to it
      2. Set mtime to updated_ts (newer) → birthtime stays at step 1
    """
    created_dt = _utc_to_local(created_ts)
    updated_dt = _utc_to_local(updated_ts)
    if not created_dt or not updated_dt:
        return

    created_epoch = created_dt.timestamp()
    updated_epoch = updated_dt.timestamp()

    # Step 1: pull birthtime back to the conversation creation time
    os.utime(path, (created_epoch, created_epoch))
    # Step 2: set mtime to the last update time; birthtime stays early
    os.utime(path, (updated_epoch, updated_epoch))


def _set_file_times_from_conv(path: Path, conv: dict):
    """Set file birthtime/mtime from the first and last message timestamps."""
    messages = conv.get("chat_messages", [])
    if not messages:
        created = conv.get("created_at", "")
        updated = conv.get("updated_at", "") or created
    else:
        created = messages[0].get("created_at", "") or conv.get("created_at", "")
        updated = messages[-1].get("created_at", "") or conv.get("updated_at", "")
    if created and updated:
        _set_file_times(path, created, updated)


def write_conversation_json(conv: dict, json_dir: Path = JSON_DIR) -> Path:
    """Write a merged conversation to json/{uuid}.json."""
    json_dir.mkdir(parents=True, exist_ok=True)
    path = json_dir / f"{conv['uuid']}.json"

    output = {k: v for k, v in conv.items() if k != "_source"}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    _set_file_times_from_conv(path, conv)
    logger.info("Wrote JSON: %s", path.name)
    return path


def write_conversation_md(conv: dict, md_dir: Path = MD_DIR) -> Path:
    """Write a conversation as a readable Markdown file."""
    md_dir.mkdir(parents=True, exist_ok=True)

    filename = build_md_filename(conv, md_dir=md_dir)
    path = md_dir / filename

    lines = []
    lines.append(f"<!-- uuid: {conv['uuid']} -->")
    lines.append(f"# {conv.get('name', 'Untitled')}\n")

    created = _local_date(conv.get("created_at", ""))
    updated = _local_date(conv.get("updated_at", ""))
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
        timestamp = _local_datetime(msg.get("created_at", ""))

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

    _set_file_times_from_conv(path, conv)
    logger.info("Wrote MD: %s", filename)
    return path


def build_md_filename(conv: dict, md_dir: Path = MD_DIR) -> str:
    """Build a safe filename like '对话标题_2026-03-07.md'."""
    title = conv.get("name", "Untitled")
    created = _local_date(conv.get("created_at", ""))

    safe_title = sanitize_filename(title)
    if not safe_title:
        safe_title = conv["uuid"][:8]

    if len(safe_title) > MAX_FILENAME_LEN:
        safe_title = safe_title[:MAX_FILENAME_LEN]

    base = f"{safe_title}_{created}" if created else safe_title

    candidate = f"{base}.md"
    existing = md_dir / candidate
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
    """Extract readable text from a message, including tool_use/tool_result."""
    content_blocks = msg.get("content", [])

    has_tool = any(
        isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
        for b in content_blocks
    )
    if not has_tool:
        text = msg.get("text", "")
        if text:
            return text
    parts = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")

        if btype == "text":
            parts.append(block.get("text", ""))

        elif btype == "tool_use":
            name = block.get("name", "tool")
            inp = block.get("input", {})
            parts.append(f"**[工具调用: {name}]**")
            if isinstance(inp, dict):
                rendered = _render_tool_input(inp)
                if rendered:
                    parts.append(rendered)

        elif btype == "tool_result":
            content = block.get("content", [])
            if isinstance(content, str) and content:
                parts.append(f"**[工具结果]**\n\n{content}")
            elif isinstance(content, list):
                for sub in content:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        raw = sub.get("text", "")
                        parts.append(f"**[工具结果]**\n\n{_try_format_json(raw)}")

    return "\n\n".join(p for p in parts if p)


def _render_tool_input(inp: dict) -> str:
    """Render tool input as readable Markdown."""
    kind = inp.get("kind", "")
    variants = inp.get("variants", [])

    if kind == "email" and variants:
        sections = []
        for v in variants:
            label = v.get("label", "")
            subject = v.get("subject", "")
            body = v.get("body", "")
            header = f"**{label}**" if label else ""
            if subject:
                header += f"\n> Subject: {subject}"
            if header:
                sections.append(header)
            if body:
                sections.append(body)
        return "\n\n".join(sections)

    if inp:
        return _try_format_json(json.dumps(inp, ensure_ascii=False))
    return ""


def _try_format_json(text: str) -> str:
    """If text is a JSON string, pretty-print it; otherwise return as-is."""
    try:
        parsed = json.loads(text)
        return "```json\n" + json.dumps(parsed, ensure_ascii=False, indent=2) + "\n```"
    except (json.JSONDecodeError, TypeError):
        return text


def write_memories(memories_data, export_date: str, memories_dir: Path = MEMORIES_DIR) -> Path | None:
    """Write memories to memories/memories_YYYY-MM-DD.json."""
    if not memories_data:
        return None

    memories_dir.mkdir(parents=True, exist_ok=True)
    filename = f"memories_{export_date}.json"
    path = memories_dir / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(memories_data, f, ensure_ascii=False, indent=2)

    logger.info("Wrote memories: %s", filename)
    return path


def cleanup_stale_md(conv: dict, md_dir: Path = MD_DIR):
    """Remove old md files for a conversation if the title changed."""
    uuid = conv["uuid"]
    current_filename = build_md_filename(conv, md_dir=md_dir)

    for md_file in md_dir.glob("*.md"):
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
