"""
Local read-only archive status API for browser userscripts.

The server binds only to 127.0.0.1 and answers CORS requests from ChatGPT
origins. It never writes archive data; it only compares current browser message
IDs with the local merged JSON for a conversation.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from config import STATUS_ALLOWED_ORIGINS, STATUS_HOST, STATUS_PORT, archive_dirs_for_platform
from parser import load_json_unicode_safe

logger = logging.getLogger(__name__)


def start_status_server(host: str = STATUS_HOST, port: int = STATUS_PORT) -> ThreadingHTTPServer:
    """Start the local status HTTP server in a background thread."""
    server = ThreadingHTTPServer((host, port), StatusRequestHandler)
    thread = Thread(target=server.serve_forever, name="llm-archive-status-server", daemon=True)
    thread.start()
    logger.info("Status server listening on http://%s:%d", host, port)
    return server


class StatusRequestHandler(BaseHTTPRequestHandler):
    server_version = "LLMArchiveStatus/1.0"

    def log_message(self, fmt: str, *args):
        logger.debug("status API: " + fmt, *args)

    def do_OPTIONS(self):
        if not self._origin_allowed():
            self._send_json({"error": "origin_not_allowed"}, status=403)
            return
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != "/status":
            self._send_json({"error": "not_found"}, status=404)
            return
        if not self._origin_allowed():
            self._send_json({"error": "origin_not_allowed"}, status=403)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        try:
            body = self.rfile.read(min(length, 2_000_000))
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "invalid_json"}, status=400)
            return

        self._send_json(build_status(payload))

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not_found"}, status=404)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in STATUS_ALLOWED_ORIGINS

    def _send_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin in STATUS_ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")

    def _send_json(self, data: dict[str, Any], status: int = 200):
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def build_status(payload: dict[str, Any]) -> dict[str, Any]:
    platform = payload.get("platform") or "CHATGPT"
    conv_uuid = payload.get("uuid") or payload.get("conversation_id")
    current_messages = _normalize_current_messages(payload.get("messages"))
    current_count = len(current_messages)
    current_human_count = sum(1 for msg in current_messages if msg.get("sender") == "human")

    if not conv_uuid:
        return {
            "status": "no_conversation",
            "exists": False,
            "synced": False,
            "message": "No conversation id",
        }

    path = archive_dirs_for_platform(platform)["json"] / f"{conv_uuid}.json"
    if not path.exists():
        return {
            "status": "not_archived",
            "exists": False,
            "synced": False,
            "platform": platform,
            "uuid": conv_uuid,
            "local_message_count": 0,
            "current_message_count": current_count,
            "local_human_count": 0,
            "current_human_count": current_human_count,
            "behind_messages": current_count,
            "behind_turns": current_human_count,
        }

    try:
        local = load_json_unicode_safe(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "read_error",
            "exists": True,
            "synced": False,
            "platform": platform,
            "uuid": conv_uuid,
            "error": str(exc),
        }

    local_messages = _normalize_current_messages(local.get("chat_messages", []))
    local_ids = {msg["uuid"] for msg in local_messages if msg.get("uuid")}
    current_ids = {msg["uuid"] for msg in current_messages if msg.get("uuid")}
    missing_ids = sorted(current_ids - local_ids)
    missing_turns = sum(
        1
        for msg in current_messages
        if msg.get("uuid") in missing_ids and msg.get("sender") == "human"
    )

    local_count = len(local_messages)
    local_human_count = sum(1 for msg in local_messages if msg.get("sender") == "human")
    count_delta = max(current_count - local_count, 0)
    human_delta = max(current_human_count - local_human_count, 0)

    if current_ids:
        behind_messages = len(missing_ids)
        behind_turns = missing_turns
        compare_mode = "message_ids"
    else:
        behind_messages = count_delta
        behind_turns = human_delta
        compare_mode = "counts"

    status = "synced" if behind_messages == 0 and current_count <= local_count else "behind"
    return {
        "status": status,
        "exists": True,
        "synced": status == "synced",
        "platform": platform,
        "uuid": conv_uuid,
        "compare_mode": compare_mode,
        "local_message_count": local_count,
        "current_message_count": current_count,
        "local_human_count": local_human_count,
        "current_human_count": current_human_count,
        "behind_messages": behind_messages,
        "behind_turns": behind_turns,
        "missing_message_ids": missing_ids[:50],
        "local_updated_at": local.get("updated_at"),
        "current_updated_at": payload.get("updated_at"),
        "path": str(path),
    }


def _normalize_current_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []

    normalized = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        uuid = msg.get("uuid") or msg.get("id")
        if not uuid:
            continue
        sender = msg.get("sender") or msg.get("role") or ""
        if sender == "user":
            sender = "human"
        normalized.append(
            {
                "uuid": str(uuid),
                "sender": sender,
                "created_at": msg.get("created_at"),
                "updated_at": msg.get("updated_at"),
            }
        )
    return normalized
