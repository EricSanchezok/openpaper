from app.llm.utils import find_offsets


def test_find_offsets_returns_exact_span() -> None:
    assert find_offsets("paper", "read the paper today") == (9, 14)


def test_find_offsets_returns_actual_fuzzy_span() -> None:
    assert find_offsets("paper result", "the paper finding") == (4, 10)
