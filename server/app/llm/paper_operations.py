import logging
import uuid
from typing import AsyncGenerator, Literal, Sequence

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.models import ReasoningLevel
from app.llm.base import BaseLLMClient
from app.llm.citation_handler import CitationHandler
from app.llm.prompts import (
    ANSWER_PAPER_QUESTION_SYSTEM_PROMPT,
    ANSWER_PAPER_QUESTION_USER_MESSAGE,
    CONCISE_MODE_INSTRUCTIONS,
    DETAILED_MODE_INSTRUCTIONS,
    GENERATE_NARRATIVE_SUMMARY,
    NORMAL_MODE_INSTRUCTIONS,
)
from app.llm.backend import SupplementaryContent, TextContent
from app.modules.conversations.application.contracts.messages import ResponseStyle
from app.modules.papers.application.contracts.extraction import AudioOverviewForLLM
from app.shared.application import Actor, ApplicationExecutor

logger = logging.getLogger(__name__)


class PaperOperations(BaseLLMClient):
    """Operations related to paper analysis and chat functionality"""

    def create_narrative_summary(
        self,
        document_id: str,
        user: Actor,
        executor: ApplicationExecutor[ApplicationCapabilities],
        length: Literal["short", "medium", "long"] | None = "medium",
        additional_instructions: str | None = None,
    ) -> AudioOverviewForLLM:
        """
        Create a narrative summary of the paper using the specified model
        """
        paper = executor.query(
            lambda capabilities: capabilities.paper_content.read(
                actor=user,
                document_id=uuid.UUID(document_id),
            )
        )

        audio_overview_schema = AudioOverviewForLLM.model_json_schema()

        # Word count targets for audio durations at ~150 words/min
        # short: ~3 min, medium: ~7 min, long: ~14 min
        word_count_map = {
            "short": 450,
            "medium": 1000,
            "long": 2000,
        }

        formatted_prompt = GENERATE_NARRATIVE_SUMMARY.format(
            additional_instructions=additional_instructions,
            length=word_count_map.get(str(length), word_count_map["medium"]),
            schema=audio_overview_schema,
        )

        message_content: list[TextContent | SupplementaryContent] = [
            SupplementaryContent(
                label="paper",
                content=str(paper.raw_content or ""),
            ),
            TextContent(text=formatted_prompt),
        ]

        # Generate narrative summary using the LLM
        response = self.generate_content(
            contents=message_content,
            response_model=AudioOverviewForLLM,
        )

        return AudioOverviewForLLM.model_validate_json(response.text)

    async def chat_with_paper(
        self,
        document_id: str,
        conversation_id: str,
        question: str,
        current_user: Actor,
        executor: ApplicationExecutor[ApplicationCapabilities],
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        user_references: Sequence[str] | None = None,
        response_style: str | None = "normal",
    ) -> AsyncGenerator[str | dict[str, object], None]:
        """
        Chat with the paper using the specified model
        """

        user_citations = (
            CitationHandler.convert_references_to_citations(user_references)
            if user_references
            else None
        )

        paper = executor.query(
            lambda capabilities: capabilities.paper_content.read(
                actor=current_user,
                document_id=uuid.UUID(document_id),
            )
        )

        casted_conversation_id = uuid.UUID(conversation_id)

        conversation_history = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=casted_conversation_id,
            )
        )

        additional_instructions = ""

        if response_style == ResponseStyle.DETAILED:
            additional_instructions = DETAILED_MODE_INSTRUCTIONS
        elif response_style == ResponseStyle.CONCISE:
            additional_instructions = CONCISE_MODE_INSTRUCTIONS
        else:
            additional_instructions = NORMAL_MODE_INSTRUCTIONS

        formatted_system_prompt = ANSWER_PAPER_QUESTION_SYSTEM_PROMPT.format(
            additional_instructions=additional_instructions,
        )

        formatted_prompt = ANSWER_PAPER_QUESTION_USER_MESSAGE.format(
            question=f"{question}\n\n{user_citations}" if user_citations else question,
        )

        evidence_buffer: list[str] = []
        text_buffer: str = ""
        in_evidence_section = False

        START_DELIMITER = "---EVIDENCE---"
        END_DELIMITER = "---END-EVIDENCE---"

        message_content: list[TextContent | SupplementaryContent] = [
            SupplementaryContent(
                label="paper",
                content=str(paper.raw_content or ""),
            ),
            TextContent(text=formatted_prompt),
        ]

        # Chat with the paper using the LLM
        for chunk in self.send_message_stream(
            message=message_content,
            system_prompt=formatted_system_prompt,
            history=conversation_history,
            reasoning_level=reasoning_level,
        ):
            if chunk.thinking:
                yield {"type": "reasoning", "content": chunk.thinking}
            text = chunk.text

            logger.debug(f"Received chunk: {text}")

            if not text:
                continue

            text_buffer += text

            # Check for start delimiter
            if not in_evidence_section and START_DELIMITER in text_buffer:
                in_evidence_section = True
                # Split at delimiter and yield any content that came before
                pre_evidence = text_buffer.split(START_DELIMITER)[0]
                if pre_evidence:
                    yield {"type": "content", "content": pre_evidence}
                # Start the evidence buffer
                evidence_buffer = [text_buffer.split(START_DELIMITER)[1]]
                # Clear the text buffer
                text_buffer = ""
                continue

            reconstructed_buffer = "".join(evidence_buffer + [text_buffer]).strip()

            if in_evidence_section and END_DELIMITER in reconstructed_buffer:
                # Find the position of the delimiter in the reconstructed buffer
                delimiter_pos = reconstructed_buffer.find(END_DELIMITER)
                evidence_part = reconstructed_buffer[:delimiter_pos]
                remaining = reconstructed_buffer[delimiter_pos + len(END_DELIMITER) :]

                # Parse the complete evidence block
                structured_evidence = CitationHandler.parse_evidence_block(
                    evidence_part
                )

                # Yield both raw and structured evidence
                yield {
                    "type": "references",
                    "content": {
                        "citations": structured_evidence,
                    },
                }

                # Reset buffers and state
                in_evidence_section = False
                evidence_buffer = []
                text_buffer = remaining

                # Yield any remaining content after evidence section
                if remaining:
                    yield {"type": "content", "content": remaining}
                continue

            # Handle normal streaming
            if in_evidence_section:
                evidence_buffer.append(text)
                text_buffer = ""
            else:
                # Keep a reasonable buffer size for detecting delimiters
                if len(text_buffer) > len(START_DELIMITER) * 2:
                    to_yield = text_buffer[: -len(START_DELIMITER)]
                    yield {"type": "content", "content": to_yield}
                    text_buffer = text_buffer[-len(START_DELIMITER) :]

        if text_buffer:
            yield {"type": "content", "content": text_buffer}


paper_operations = PaperOperations()
