# LLM Chat Archiver

Watches `~/Downloads` for Claude and ChatGPT conversation exports and archives them with incremental message-level deduplication.

## What It Does

- **Monitors** `~/Downloads` for:
  - Claude full exports: `data-*.zip`
  - Claude single exports: `Claude_*.json`
  - ChatGPT single exports: `ChatGPT_*.json`
- **Ingests** new exports into platform-specific archive directories.
- **Merges** conversations at the message level — union of all messages by UUID, so nothing is lost.
- **Outputs** clean JSON and readable Markdown per conversation.
- **Decodes** Unicode escapes and surrogate pairs into actual characters.

## Archive Structure

```text
~/Archive/LLMs-chat/
├── Claude/
│   ├── full/
│   ├── single/
│   ├── json/
│   ├── memories/
│   └── *.md
└── ChatGPT/
    ├── single/
    ├── json/
    └── *.md
```

Claude and ChatGPT share the same normalized conversation schema:

- `uuid`, `name`, `summary`, `model`, `created_at`, `updated_at`
- `account`, `settings`, `platform`, `is_starred`
- `chat_messages[]` with `uuid`, `text`, `content`, `sender`, timestamps, attachments, and parent message UUID

## Usage

```bash
pip install -r requirements.txt

# One-time full scan of existing ingested exports
python main.py --scan

# Watch for new exports
python main.py --daemon

# Scan first, then watch
python main.py --scan --daemon
```

## Export Scripts

- `claude-exporter.user.js` exports Claude conversations as the existing Claude-compatible JSON.
- `chatgpt-exporter.user.js` exports ChatGPT conversations in the same normalized schema and downloads files named `ChatGPT_<title>_<timestamp>.json`.

Install the relevant userscript with Tampermonkey or Violentmonkey, export a conversation, and the watcher will move it from `~/Downloads` into the correct platform archive.

## Dedup Strategy

For the same conversation UUID across multiple exports:

1. Collect all messages from every source.
2. Deduplicate by message UUID.
3. If the same message appears in multiple sources, keep the one with the latest `updated_at`.
4. Conversation metadata comes from the newest source.
5. Final messages are sorted by `created_at`.

This preserves incremental exports without duplicating unchanged messages.
