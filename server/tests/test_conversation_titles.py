"""Initial Conversation title generation rules."""

from types import SimpleNamespace

import pytest

from app.llm.conversation_titles import should_generate_initial_title


@pytest.mark.parametrize(
    ("title_is_default", "roles", "expected"),
    [
        (True, ["user", "assistant"], True),
        (True, ["user", "user", "assistant"], True),
        (True, ["user"], False),
        (True, ["user", "assistant", "user", "assistant"], False),
        (False, ["user", "assistant"], False),
    ],
)
def test_initial_title_is_generated_after_only_the_first_assistant_reply(
    title_is_default: bool,
    roles: list[str],
    expected: bool,
) -> None:
    history = [SimpleNamespace(role=role, content=role) for role in roles]

    assert (
        should_generate_initial_title(
            title_is_default=title_is_default,
            chat_history=history,
        )
        is expected
    )
