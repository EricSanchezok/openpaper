from app.helpers.anysearch_search import _parse_markdown_results


def test_parse_anysearch_markdown_results() -> None:
    results = _parse_markdown_results(
        """## Search Results (1 result)

### 1. Example paper
- **URL**: https://example.org/paper
- Useful research summary.
"""
    )

    assert len(results) == 1
    assert results[0].title == "Example paper"
    assert results[0].url == "https://example.org/paper"
    assert results[0].text == "- Useful research summary."
