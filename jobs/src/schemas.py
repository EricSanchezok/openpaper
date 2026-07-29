"""
Pydantic schemas for PDF processing.
"""

from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResponseCitation(BaseModel):
    """
    Schema for a citation in the paper.
    This is used to represent a single citation with its text and context.
    """

    text: str = Field(
        description="The raw text of the citation as it appears in the paper. Ensure that this is a direct quote or paraphrase from the paper."
    )
    index: int = Field(
        description="The index of the citation in the paper's reference list. This is used to identify the citation in discussions or findings."
    )


class HighlightType(str, Enum):
    TOPIC = "topic"
    MOTIVATION = "motivation"
    METHOD = "method"
    EVIDENCE = "evidence"
    RESULT = "result"
    IMPACT = "impact"


class AIHighlight(BaseModel):
    """
    Schema for a highlight in the paper.
    This is used to represent a single highlight with its text and context.
    """

    text: str = Field(
        description="The raw text of the highlight as it appears in the paper. Ensure that this is a direct quote or paraphrase from the paper."
    )
    annotation: str = Field(
        description="The context or annotation for the highlight, explaining its significance or relevance to the paper's content. Less than 350 characters."
    )

    type: HighlightType = Field(
        description="The type of highlight. This can be one of the following: topic, motivation, method, evidence, result, impact. This helps categorize the highlight based on its content and significance."
    )


class TitleAuthorsAbstract(BaseModel):
    """Schema for title, authors, and abstract extraction."""

    title: str = Field(description="Title of the paper **in normal case**")
    authors: list[str] = Field(default_factory=list, description="List of authors")
    abstract: str = Field(default="", description="Abstract of the paper")
    publish_date: str | None = Field(
        default="", description="Publishing date of the paper in YYYY-MM-DD format"
    )


class InstitutionsKeywords(BaseModel):
    """Schema for institutions and keywords extraction."""

    institutions: list[str] = Field(
        default_factory=list,
        description="List of institutions involved in the publication.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "3-8 concise topical keywords describing the paper's subject. "
            "Write each in title case (e.g. 'Machine Learning', 'Protein Folding'), "
            "NOT normal case or ALL CAPS; capitalize only proper nouns and acronyms "
            "(e.g. 'CRISPR', 'BERT', 'Alzheimer's Disease'). Prefer established field "
            "or topic terms, keep each to a short phrase (not a sentence), and do not "
            "repeat near-duplicates."
        ),
    )


class SummaryAndCitations(BaseModel):
    """Schema for summary and citations extraction."""

    summary_citations: list[ResponseCitation] = Field(
        description="List of citations supporting the summary. Include direct quotes or paraphrases with the citation index. The index should match the inline citations used in the summary. Only include citations that are directly relevant to the summary content. Use sequential numbering starting from 1."
    )
    summary: str = Field(
        description="""
            Generate a concise summary of the research paper (< 200 words) that captures the essential contribution for readers with basic domain knowledge. Break each of the sections up for clarity. Separate sections with blank lines to ensure proper paragraph breaks in markdown. Do not use literal `\n` characters for line breaks. Do not use separate headings for each section.

            ## Structure:
            Write 1-2 sentences on each section covering:
            1. **Background**: What gap or question does this address?
            2. **Methodology**: What methods, datasets, or techniques were used?
            3. **Findings**: What were the main results? What are the implications? Include specific metrics when available.

            ## Citation Requirements:
            - Use inline citations [^1], [^2] to support factual claims, especially numerical results. The citation index should match the corresponding entry in the `summary_citations` field.
            - Use sequential numbering starting from [^1]

            ## Quality Standards:
            - Write in clear, accessible language while maintaining technical accuracy
            - Focus on the paper's primary contribution—omit secondary findings
            - Present findings objectively, including limitations when relevant
            - If constrained for length, prioritize key results and implications

            The goal is a focused, readable paragraph that gives someone a quick understanding of what the paper accomplishes.
                    """,
    )


class Highlights(BaseModel):
    """Schema for highlights extraction."""

    highlights: list[AIHighlight] = Field(
        default_factory=list,
        description="""
Extract 3-5 standout highlights that capture the most compelling and unique aspects of this research paper. Focus on what makes this paper distinctive rather than summarizing standard content.

Requirements for Highlights:
- Each highlight should be a direct, exact quote from the paper
- Each highlight must be accompanied by a brief annotation (1-2 sentences) explaining its significance or relevance to the paper's contributions

Selection Criteria:
Prioritize highlights that are:
- Novel or surprising: Unexpected findings, counterintuitive results, or breakthrough discoveries
- Methodologically innovative: New techniques, creative experimental designs, or unique approaches
- High-impact insights: Findings that could change how the field thinks about a problem
- Quantitatively significant: Impressive performance gains, large effect sizes, or notable statistical findings
- Practically valuable: Real-world applications, actionable implications, or scalable solutions

Content Sources:
- Key results from tables/figures: Extract specific metrics, comparisons, or visual insights
- Critical methodology details: Novel algorithms, experimental setups, or analytical approaches
- Standout conclusions: Bold claims, important limitations, or paradigm-shifting implications
- Notable observations: Interesting patterns, unexpected behaviors, or important caveats

Quality Guidelines:
- Selectivity: Choose only the most essential "must-read" elements—what would experts in the field find most noteworthy?
- Specificity: Prefer concrete findings over general statements
- Diversity: Ensure highlights span different aspects (methods, results, implications) and types, without referencing the abstract
- Context: Each annotation should explain *why* this highlight matters to the broader research landscape

What to Avoid:
- Generic background information or literature review content
- Standard methodology descriptions unless truly innovative
- Routine experimental procedures or common practices
- Abstract-level summaries that don't reveal paper specifics
- Redundant highlights that convey similar information
- Snippets that are pulled directly from the abstract or summary

Think: "If I could only share 3-5 insights from this paper with a colleague, what would make them most excited to read the full work?"
""",
    )


class PaperMetadataExtraction(BaseModel):
    """Extracted metadata from a paper"""

    title: str = Field(description="Title of the paper in normal case")
    authors: list[str] = Field(default_factory=list, description="List of authors")
    abstract: str = Field(default="", description="Abstract of the paper")
    institutions: list[str] = Field(
        default_factory=list,
        description="List of institutions involved in the publication.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "3-8 concise topical keywords describing the paper's subject. "
            "Write each in title case (e.g. 'Machine Learning', 'Protein Folding'), "
            "NOT normal case or ALL CAPS; capitalize only proper nouns and acronyms "
            "(e.g. 'CRISPR', 'BERT', 'Alzheimer's Disease'). Prefer established field "
            "or topic terms, keep each to a short phrase (not a sentence), and do not "
            "repeat near-duplicates."
        ),
    )
    summary: str = Field(
        default="",
        description="""
A concise, well-structured summary of the paper in markdown format. Include:
1. Key findings and contributions
2. Research methodology
3. Results and implications
4. Potential applications or impact

Format guidelines:
- Optional opening title (under 10 words)
- First paragraph: 2-4 sentence overview of the paper
- Use clear headings, bullet points, and tables for organization
- Include relevant data points and metrics when available
- Use plain language while preserving technical accuracy
- Include inline citations to support claims that refer to the paper's content. This is especially important for claims about the findings, methodology, and results.

Citation guidelines:
- Use [^1], [^2], [^6, ^7] etc. for citations in the summary
- Always increase the index of the citation sequentially, starting from 1
- You will separately provide a list of citations in the `summary_citations` field with the raw text and index

The summary should be accessible to readers with basic domain knowledge while maintaining scientific integrity.
                         """,
    )
    summary_citations: list[ResponseCitation] = Field(
        default_factory=list,
        description="List of citations that are relevant to the summary. These should be direct quotes or paraphrases from the paper that support the summary provided. Remember to include the citation index (e.g., [^1], [^2]) in the summary.",
    )
    publish_date: str | None = Field(
        default=None, description="Publishing date of the paper in YYYY-MM-DD format"
    )
    highlights: list[AIHighlight] = Field(
        default_factory=list,
        description="List of key highlights from the paper. These should be significant quotes that are must-reads of the paper's findings and contributions. Each highlight should include the text of the highlight and an annotation explaining its significance or relevance to the paper's content. Particularly drill into interesting, novel findings, methodologies, or implications that are worth noting. Pay special attention to tables, figures, and diagrams that may contain important information.",
    )


class PDFProcessingResult(BaseModel):
    """Result of PDF processing"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: str
    raw_content: str | None = None
    page_offset_map: dict[int, list[int]] | None = None
    metadata: PaperMetadataExtraction | None = None
    s3_object_key: str | None = None
    preview_s3_key: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: Literal["mineru", "pymupdf"] | None = None
    parser_quality: Literal["full", "text_only"] | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    error: str | None = None
    duration: float | None = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "PDFProcessingResult":
        if self.success:
            if (
                not self.raw_content
                or not self.page_offset_map
                or self.parser_backend is None
                or self.parser_quality is None
                or not self.parser_version
            ):
                raise ValueError("successful PDF result is incomplete")
        elif not self.error:
            raise ValueError("failed PDF result requires an error code")
        return self


class DocumentMapping(BaseModel):
    title: str
    id: str
    raw_content: str


class DataTableSchema(BaseModel):
    columns: list[str] = Field(description="List of column names in the data table.")
    papers: list[DocumentMapping] = Field(
        description="List of papers included in the data table."
    )


class DataTableCellValue(BaseModel):
    """Value for a single cell in the data table with supporting citations."""

    value: str = Field(description="The extracted value for this column")
    citations: list[ResponseCitation] = Field(
        default_factory=list,
        description="List of citations that support this specific value. These should be direct quotes or paraphrases from the paper.",
    )


class DataTableRow(BaseModel):
    paper_id: str
    values: dict[str, DataTableCellValue]  # column_name -> cell value with citations


class DataTableResult(BaseModel):
    success: bool
    columns: list[str] = Field(description="List of column names in the data table.")
    rows: list[DataTableRow] = Field(
        default_factory=list, description="Row data per paper"
    )
    row_failures: list[str] = Field(
        default_factory=list, description="List of paper_ids that failed to process"
    )


class DataTableTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: str
    title: str | None = Field(default=None, max_length=240)
    table: DataTableSchema


class ResearchDataTableResult(BaseModel):
    research_item_id: str
    title: str | None
    columns: list[str]
    rows: list[DataTableRow]
    row_failures: list[str]


class AudioSourceDocument(BaseModel):
    id: str
    title: str
    canonical_s3_key: str


class AudioOverviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: str
    scope_type: Literal["document", "project"]
    scope_id: str
    documents: list[AudioSourceDocument] = Field(min_length=1, max_length=100)
    length: Literal["short", "medium", "long"] = "medium"
    additional_instructions: str | None = Field(default=None, max_length=10_000)


class AudioOverviewNarrative(BaseModel):
    title: str
    transcript: str
    citations: list[ResponseCitation] = Field(default_factory=list)


class AudioOverviewResult(BaseModel):
    research_item_id: str
    title: str
    transcript: str
    citations: list[ResponseCitation]
    s3_object_key: str
    voice_id: str
    model_version: str
