from pathlib import Path

DOWNLOADS_DIR = Path.home() / "Downloads"
ARCHIVE_ROOT = Path.home() / "Archive" / "LLMs-chat" / "Claude"

FULL_DIR = ARCHIVE_ROOT / "full"
SINGLE_DIR = ARCHIVE_ROOT / "single"
JSON_DIR = ARCHIVE_ROOT / "json"
MEMORIES_DIR = ARCHIVE_ROOT / "memories"
MD_DIR = ARCHIVE_ROOT  # md files go directly in the archive root

# Patterns for detecting Claude exports in Downloads
FULL_EXPORT_PATTERN = r"^data-\d{4}-\d{2}-\d{2}-.*\.zip$"
SINGLE_EXPORT_PATTERN = r"^Claude_.+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}\.json$"
SINGLE_EXPORT_MD_PATTERN = r"^Claude_.+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}\.md$"

# Debounce delay (seconds) to wait for file write completion
DEBOUNCE_SECONDS = 2.0
