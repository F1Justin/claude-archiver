from pathlib import Path

DOWNLOADS_DIR = Path.home() / "Downloads"
ARCHIVE_BASE = Path.home() / "Archive" / "LLMs-chat"

PLATFORM_ROOTS = {
    "CLAUDE_AI": ARCHIVE_BASE / "Claude",
    "CHATGPT": ARCHIVE_BASE / "ChatGPT",
}

# Backward-compatible defaults for existing Claude archive functions/callers.
ARCHIVE_ROOT = PLATFORM_ROOTS["CLAUDE_AI"]
FULL_DIR = ARCHIVE_ROOT / "full"
SINGLE_DIR = ARCHIVE_ROOT / "single"
JSON_DIR = ARCHIVE_ROOT / "json"
MEMORIES_DIR = ARCHIVE_ROOT / "memories"
MD_DIR = ARCHIVE_ROOT  # md files go directly in the archive root

# Patterns for detecting exports in Downloads
FULL_EXPORT_PATTERN = r"^data-\d{4}-\d{2}-\d{2}-.*\.zip$"
SINGLE_EXPORT_PATTERN = r"^Claude_.+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}\.json$"
SINGLE_EXPORT_MD_PATTERN = r"^Claude_.+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}\.md$"
CHATGPT_SINGLE_EXPORT_PATTERN = r"^ChatGPT_.+_\d{4}-\d{2}-\d{2}T.*\.json$"
CHATGPT_SINGLE_EXPORT_MD_PATTERN = r"^ChatGPT_.+_\d{4}-\d{2}-\d{2}T.*\.md$"

SINGLE_EXPORT_PATTERNS = (
    ("CLAUDE_AI", SINGLE_EXPORT_PATTERN),
    ("CHATGPT", CHATGPT_SINGLE_EXPORT_PATTERN),
)

SINGLE_EXPORT_MD_PATTERNS = (
    ("CLAUDE_AI", SINGLE_EXPORT_MD_PATTERN),
    ("CHATGPT", CHATGPT_SINGLE_EXPORT_MD_PATTERN),
)


def archive_root_for_platform(platform: str | None) -> Path:
    """Return the archive root for a normalized conversation platform."""
    return PLATFORM_ROOTS.get(platform or "", PLATFORM_ROOTS["CLAUDE_AI"])


def archive_dirs_for_platform(platform: str | None) -> dict[str, Path]:
    """Return standard archive directories for a platform."""
    root = archive_root_for_platform(platform)
    return {
        "root": root,
        "full": root / "full",
        "single": root / "single",
        "json": root / "json",
        "memories": root / "memories",
        "md": root,
    }


def platform_for_single_export_name(name: str) -> str | None:
    """Infer platform from a single-export filename."""
    import re

    for platform, pattern in SINGLE_EXPORT_PATTERNS:
        if re.match(pattern, name):
            return platform
    return None


def platform_for_single_export_md_name(name: str) -> str | None:
    """Infer platform from a single-export markdown companion filename."""
    import re

    for platform, pattern in SINGLE_EXPORT_MD_PATTERNS:
        if re.match(pattern, name):
            return platform
    return None

# Debounce delay (seconds) to wait for file write completion
DEBOUNCE_SECONDS = 2.0
