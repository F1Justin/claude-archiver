"""
Message-level merge/dedup engine for LLM conversations.

Merges conversations by UUID, taking the union of all messages (by message UUID)
so that no content is ever lost. When the same message appears in multiple sources,
the version with the latest updated_at wins.
"""

import json
import logging
from pathlib import Path

from config import JSON_DIR
from parser import _deep_decode_unicode

logger = logging.getLogger(__name__)


def merge_all_conversations(conversation_groups: dict[str, list[dict]], json_dir: Path = JSON_DIR) -> list[dict]:
    """
    Merge conversations from all sources.

    Args:
        conversation_groups: {conv_uuid: [conv_dict, conv_dict, ...]}
            Each conv_uuid may have multiple versions from different exports.

    Returns:
        List of merged conversation dicts.
    """
    merged = []
    for conv_uuid, versions in conversation_groups.items():
        existing = load_existing_json(conv_uuid, json_dir=json_dir)
        if existing:
            versions.insert(0, existing)
        result = merge_conversation_versions(versions)
        merged.append(result)
    return merged


def merge_conversation_versions(versions: list[dict]) -> dict:
    """
    Merge multiple versions of the same conversation into one.

    Strategy:
    - Messages: union by message UUID, latest updated_at wins per message
    - Metadata: take from the version with the latest updated_at
    """
    if len(versions) == 1:
        return versions[0]

    versions_sorted = sorted(versions, key=lambda v: v.get("updated_at", ""))
    latest = versions_sorted[-1]

    all_messages: dict[str, dict] = {}
    for version in versions_sorted:
        for msg in version.get("chat_messages", []):
            msg_uuid = msg.get("uuid", "")
            if not msg_uuid:
                continue
            existing = all_messages.get(msg_uuid)
            if existing is None or msg.get("updated_at", "") >= existing.get("updated_at", ""):
                all_messages[msg_uuid] = msg

    merged_messages = sorted(all_messages.values(), key=lambda m: m.get("created_at", ""))

    result = {
        "uuid": latest["uuid"],
        "name": latest.get("name", "Untitled"),
        "summary": latest.get("summary", ""),
        "model": latest.get("model", "") or _find_field_in_versions(versions_sorted, "model"),
        "created_at": min(v.get("created_at", "") for v in versions_sorted if v.get("created_at")) or "",
        "updated_at": latest.get("updated_at", ""),
        "account": latest.get("account", {}),
        "settings": latest.get("settings", {}) or _find_field_in_versions(versions_sorted, "settings"),
        "platform": latest.get("platform", "") or _find_field_in_versions(versions_sorted, "platform"),
        "is_starred": latest.get("is_starred", False),
        "chat_messages": merged_messages,
    }
    return result


def _find_field_in_versions(versions: list[dict], field: str):
    """Find the first non-empty value for a field across versions (latest-first)."""
    for v in reversed(versions):
        val = v.get(field)
        if val:
            return val
    return "" if field != "settings" else {}


def load_existing_json(conv_uuid: str, json_dir: Path = JSON_DIR) -> dict | None:
    """Load an existing merged conversation from json/ if it exists."""
    path = json_dir / f"{conv_uuid}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _deep_decode_unicode(json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load existing %s: %s", path, e)
        return None


def group_conversations(all_conversations: list[dict]) -> dict[str, list[dict]]:
    """Group a flat list of conversations by their UUID."""
    groups: dict[str, list[dict]] = {}
    for conv in all_conversations:
        uuid = conv["uuid"]
        groups.setdefault(uuid, []).append(conv)
    return groups


def count_new_rounds(conv_uuid: str, new_conv: dict, json_dir: Path = JSON_DIR) -> int:
    """Count how many new human-assistant rounds were added compared to stored version."""
    existing = load_existing_json(conv_uuid, json_dir=json_dir)
    old_uuids = {m["uuid"] for m in existing.get("chat_messages", [])} if existing else set()
    new_human = sum(
        1 for m in new_conv.get("chat_messages", [])
        if m["uuid"] not in old_uuids and m.get("sender") == "human"
    )
    return max(new_human, 1) if not existing else new_human


def has_changed(conv_uuid: str, new_conv: dict, json_dir: Path = JSON_DIR) -> bool:
    """Check if a conversation has actually changed compared to the stored version."""
    existing = load_existing_json(conv_uuid, json_dir=json_dir)
    if existing is None:
        return True

    existing_msg_uuids = {m["uuid"] for m in existing.get("chat_messages", [])}
    new_msg_uuids = {m["uuid"] for m in new_conv.get("chat_messages", [])}
    if existing_msg_uuids != new_msg_uuids:
        return True

    if existing.get("updated_at", "") != new_conv.get("updated_at", ""):
        return True

    if existing.get("name") != new_conv.get("name"):
        return True

    if existing.get("summary") != new_conv.get("summary"):
        return True

    if _message_signature(existing) != _message_signature(new_conv):
        return True

    return False


def _message_signature(conv: dict) -> str:
    """Stable message-content signature used to catch exporter/schema fixes."""
    fields = (
        "uuid",
        "text",
        "content",
        "sender",
        "created_at",
        "updated_at",
        "attachments",
        "files",
        "files_v2",
        "parent_message_uuid",
        "model",
    )
    messages = [
        {field: msg.get(field) for field in fields if field in msg}
        for msg in conv.get("chat_messages", [])
    ]
    messages.sort(key=lambda msg: (msg.get("created_at") or "", msg.get("uuid") or ""))
    return json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
