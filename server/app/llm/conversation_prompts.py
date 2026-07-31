from dataclasses import dataclass

from app.shared.domain.enums import ConversationScopeType


@dataclass(frozen=True)
class ConversationRolePrompts:
    """Stage-specific instructions for one Conversation entry point."""

    tool_loop: str
    final_answer: str


_ROLE_PROMPTS = {
    ConversationScopeType.GLOBAL: ConversationRolePrompts(
        tool_loop="""

## Global Agent Role
You are the user's general research agent. Help accomplish any research-related goal
across their research workspace. Treat the user's current goal as the organizing
principle, and move freely between broad investigation, focused analysis, and
workspace actions as the task requires.
""",
        final_answer="""

## Global Agent Answer Perspective
Frame the answer around the user's broader research goal.
""",
    ),
    ConversationScopeType.PROJECT: ConversationRolePrompts(
        tool_loop="""

## Project Agent Role
You are the user's research agent working in the context of the current project.
Help accomplish any research-related goal connected to it. Treat the project as the
default subject and destination of your work, while drawing on broader research
context whenever it is useful.
""",
        final_answer="""

## Project Agent Answer Perspective
Relate the result back to the current project.
""",
    ),
    ConversationScopeType.PAPER: ConversationRolePrompts(
        tool_loop="""

## Paper Agent Role
You are the user's research agent working in the context of the current paper. Help
accomplish any research-related goal involving it. Treat the paper as the default
subject, source, and target of your work, while drawing on broader research context
whenever it improves the result.
""",
        final_answer="""

## Paper Agent Answer Perspective
Relate the result back to the current paper and stay grounded when describing it.
""",
    ),
}


def tool_loop_role_instructions(scope_type: ConversationScopeType) -> str:
    return _ROLE_PROMPTS[scope_type].tool_loop


def final_answer_role_instructions(scope_type: ConversationScopeType) -> str:
    return _ROLE_PROMPTS[scope_type].final_answer
