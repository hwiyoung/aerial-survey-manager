"""Shared formatting utilities used across backend modules."""


def format_elapsed(seconds: float) -> str:
    """Format elapsed seconds to human-readable Korean string.

    Examples:
        format_elapsed(5)   -> "5초"
        format_elapsed(125) -> "2분 05초"
    """
    minutes, secs = divmod(int(seconds), 60)
    if minutes > 0:
        return f"{minutes}분 {secs:02d}초"
    return f"{secs}초"
