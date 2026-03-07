# Claude Chat Archiver

Watches `~/Downloads` for Claude AI chat exports and automatically archives them with incremental deduplication.

## What it does

- **Monitors** `~/Downloads` for Claude full exports (`data-*.zip`) and single conversation exports (`Claude_*.json`)
- **Ingests** new exports into an organized archive directory
- **Merges** conversations at the message level — union of all messages by UUID, so nothing is ever lost
- **Outputs** clean JSON (one file per conversation) and readable Markdown
- **Decodes** all Unicode escapes (`\uXXXX`) into actual characters

## Archive structure

```
~/Archive/LLMs-chat/Claude/
├── full/           # Raw full exports (untouched)
├── single/         # Raw single exports (untouched)
├── json/           # Merged JSON per conversation (incremental)
├── memories/       # Extracted memories with date
└── *.md            # Readable Markdown per conversation (incremental)
```

## Usage

```bash
pip install -r requirements.txt

# One-time full scan of existing exports
python main.py --scan

# Watch for new exports (daemon mode)
python main.py --daemon

# Scan first, then watch
python main.py --scan --daemon
```

## macOS auto-start

Copy the launchd plist to start on login:

```bash
cp com.justin.claude-archiver.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.justin.claude-archiver.plist
```

## Dedup strategy

For the same conversation UUID across multiple exports:

1. Collect all messages from every source (full exports + single exports + existing JSON)
2. Deduplicate by message UUID — if the same message appears in multiple sources, keep the one with the latest `updated_at`
3. Conversation metadata (title, summary) taken from the newest source
4. Final messages sorted by `created_at`

This ensures **no content is ever lost** — even if one export has messages another doesn't.
