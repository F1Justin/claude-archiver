"""
Unified parser for normalized LLM chat exports.

Handles two formats:
- Claude full export: JSON array of conversations from conversations.json
- single export: normalized conversation JSON object (Claude_*.json or ChatGPT_*.json)
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_SURROGATE_PAIR_RE = re.compile(r"\\u([dD][89aAbB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})")


def load_json_unicode_safe(path: Path) -> dict | list:
    """Load JSON file, automatically handling unicode escapes."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _deep_decode_unicode(data)


def _decode_surrogate_pair(high: int, low: int) -> str:
    """Combine a UTF-16 surrogate pair into the actual Unicode character."""
    code_point = 0x10000 + (high - 0xD800) * 0x400 + (low - 0xDC00)
    return chr(code_point)


def _fix_surrogates(s: str) -> str:
    """Replace lone surrogate chars (from json.load) with the correct codepoint."""
    result = []
    i = 0
    while i < len(s):
        c = s[i]
        cp = ord(c)
        if 0xD800 <= cp <= 0xDBFF and i + 1 < len(s):
            low = ord(s[i + 1])
            if 0xDC00 <= low <= 0xDFFF:
                result.append(_decode_surrogate_pair(cp, low))
                i += 2
                continue
        result.append(c)
        i += 1
    return "".join(result)


def _deep_decode_unicode(obj):
    """Recursively decode literal \\uXXXX sequences and fix surrogate pairs."""
    if isinstance(obj, str):
        # First fix any lone surrogates already decoded by json.load
        # (happens when source JSON has \\uD83D\\uDC4D emoji surrogate pairs)
        try:
            obj.encode("utf-8")
        except UnicodeEncodeError:
            obj = _fix_surrogates(obj)

        # Then decode any remaining literal \\uXXXX escape sequences in the text
        if "\\u" in obj:
            # Handle surrogate pairs first (\\uD83D\\uDC4D -> 👍)
            obj = _SURROGATE_PAIR_RE.sub(
                lambda m: _decode_surrogate_pair(int(m.group(1), 16), int(m.group(2), 16)),
                obj,
            )
            # Then handle remaining single escapes
            obj = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), obj)
        return obj
    if isinstance(obj, list):
        return [_deep_decode_unicode(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _deep_decode_unicode(v) for k, v in obj.items()}
    return obj


def parse_full_export_dir(dir_path: Path) -> list[dict]:
    """Parse a full export directory containing conversations.json."""
    conv_file = dir_path / "conversations.json"
    if not conv_file.exists():
        logger.warning("No conversations.json in %s", dir_path)
        return []

    data = load_json_unicode_safe(conv_file)
    if not isinstance(data, list):
        logger.warning("conversations.json is not a list in %s", dir_path)
        return []

    conversations = []
    for conv in data:
        conversations.append(normalize_conversation(conv, source=str(dir_path)))
    logger.info("Parsed %d conversations from %s", len(conversations), dir_path.name)
    return conversations


def parse_single_export(file_path: Path) -> dict | None:
    """Parse a single normalized conversation export."""
    data = load_json_unicode_safe(file_path)
    if not isinstance(data, dict) or "uuid" not in data:
        logger.warning("Invalid single export: %s", file_path)
        return None

    conv = normalize_conversation(data, source=str(file_path))
    logger.info("Parsed single conversation '%s' from %s", conv["name"], file_path.name)
    return conv


def normalize_conversation(raw: dict, source: str = "") -> dict:
    """Normalize a conversation dict to a standard internal structure."""
    messages = raw.get("chat_messages", [])
    normalized_messages = []
    for msg in messages:
        normalized_messages.append(normalize_message(msg))

    normalized_messages.sort(key=lambda m: m.get("created_at", ""))

    return {
        "uuid": raw["uuid"],
        "name": raw.get("name", "Untitled"),
        "summary": raw.get("summary", ""),
        "model": raw.get("model", ""),
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "account": raw.get("account", {}),
        "settings": raw.get("settings", {}),
        "platform": raw.get("platform", ""),
        "is_starred": raw.get("is_starred", False),
        "chat_messages": normalized_messages,
        "_source": source,
    }


def normalize_message(raw: dict) -> dict:
    """Normalize a single message dict."""
    content_blocks = raw.get("content", [])
    text = raw.get("text", "")
    if not text and content_blocks:
        text = extract_text_from_content(content_blocks)

    return {
        "uuid": raw["uuid"],
        "text": text,
        "content": content_blocks,
        "sender": raw.get("sender", ""),
        "index": raw.get("index"),
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "attachments": raw.get("attachments", []),
        "files": raw.get("files", []),
        "files_v2": raw.get("files_v2", []),
        "parent_message_uuid": raw.get("parent_message_uuid", ""),
    }


def extract_text_from_content(content_blocks: list) -> str:
    """Extract plain text from content block array."""
    parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def extract_memories(dir_path: Path) -> dict | None:
    """Extract memories.json from a full export directory if present."""
    mem_file = dir_path / "memories.json"
    if not mem_file.exists():
        return None
    data = load_json_unicode_safe(mem_file)
    logger.info("Found memories.json in %s", dir_path.name)
    return data
