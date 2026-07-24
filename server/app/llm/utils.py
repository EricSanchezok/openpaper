import difflib


def find_offsets(target: str, full_text: str) -> tuple[int, int]:
    """Find exact offsets, falling back to the longest matching span."""
    start_offset = full_text.find(target)
    if start_offset >= 0:
        return start_offset, start_offset + len(target)

    match = difflib.SequenceMatcher(None, full_text, target).find_longest_match(
        0, len(full_text), 0, len(target)
    )
    if match.size == 0:
        return -1, -1
    return match.a, match.a + match.size
