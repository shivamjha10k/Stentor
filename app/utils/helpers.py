"""
Shared utility helpers for the RAG pipeline.
"""


def truncate(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length, appending '...' if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def safe_join(items: list[str], separator: str = ", ", default: str = "none") -> str:
    """Join a list of strings safely, returning default if empty."""
    if not items:
        return default
    return separator.join(items)
