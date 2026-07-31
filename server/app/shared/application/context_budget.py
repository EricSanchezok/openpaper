"""Provider-independent helpers for bounding large text payloads."""


def estimate_tokens(value: str) -> int:
    """Conservatively estimate tokens for both English and CJK text.

    Exact tokenization is provider-specific. Three UTF-8 bytes per token
    intentionally overestimates typical English while closely approximating
    CJK text, which is safer for mixed-language content.
    """
    return max(1, (len(value.encode("utf-8")) + 2) // 3)


def truncate_to_token_budget(value: str, max_tokens: int) -> str:
    """Keep the beginning and end of text within an estimated token budget."""
    max_bytes = max_tokens * 3
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    marker = b"\n...[middle omitted for compaction input]...\n"
    if max_bytes <= len(marker):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    content_budget = max(0, max_bytes - len(marker))
    head_size = content_budget // 2
    tail_size = content_budget - head_size
    head = encoded[:head_size].decode("utf-8", errors="ignore")
    tail = encoded[-tail_size:].decode("utf-8", errors="ignore") if tail_size else ""
    return f"{head}{marker.decode()}{tail}"
