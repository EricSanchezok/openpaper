from app.shared.domain.enums import ConversationScopeType


_SCOPE_INSTRUCTIONS = {
    ConversationScopeType.PAPER: (
        "\n\nThis conversation starts from one paper. Its full text is provided as "
        "the anchor source; use tools for any other paper in the selected context."
    ),
    ConversationScopeType.PROJECT: (
        "\n\nThis conversation starts from a project. Project metadata describes "
        "the collection, but paper claims must be grounded through the evidence tools."
    ),
    ConversationScopeType.GLOBAL: (
        "\n\nThis conversation starts from the user's library. Do not assume that "
        "library metadata is paper evidence; use the evidence tools to ground claims."
    ),
}


def scope_system_instructions(scope_type: ConversationScopeType) -> str:
    return _SCOPE_INSTRUCTIONS[scope_type]
