GENERATE_NARRATIVE_SUMMARY = """
You are on an important mission to generate a narrative summary of the provided paper. Your task is to create a concise and informative summary that captures the essence of the paper, including its key findings, methodologies, and conclusions.

Your summary should be structured in a way that is easy to understand and provides a clear overview of the paper's contributions to its field. Focus on the most significant aspects of the research, avoiding unnecessary details or jargon.

If you encounter any difficult or complex concepts, explain them in simple terms to ensure clarity for a broad audience.

Your summary should be approximately {length} words long (this is important - aim to hit this target). It should be written in a narrative style that flows logically from one point to the next without abrupt transitions or special headings or formatting. The summary should be written in a way that is engaging and informative, suitable for readers who may not be experts in the field.

Write the summary in plain text, with minimal syntax formatting for citations.

Include any citations or references to specific sections of the paper, reproducing the raw text. It should read like a cohesive brief that could be read on a podcast or in a blog post.

Citations should be formatted as [^1], [^2], etc., where each number corresponds to the idx of the list of citations you will provide at the end of the summary.

{additional_instructions}

Response Schema:
{schema}
"""

GENERATE_MULTI_PAPER_NARRATIVE_SUMMARY = """
You are tasked with creating a comprehensive narrative summary based on multiple research papers.

Summary Request: {summary_request}

Evidence Gathered from Papers:
{evidence_gathered}

Paper Metadata:
{paper_metadata}

Additional Instructions: {additional_instructions}

Create a narrative summary that:
1. Synthesizes information across all relevant papers
2. Identifies key themes, trends, and insights
3. Highlights agreements and disagreements between papers
4. Provides a cohesive narrative that addresses the summary request
5. Includes proper citations and references to the source papers
6. Is approximately {length} words long (this is important - aim to hit this target)

The summary should be engaging, informative, and suitable for audio narration.

Return your response as a JSON object matching this exact schema:
{schema}
"""

RENAME_CONVERSATION_SYSTEM_PROMPT = """
You are an expert at summarizing conversations. Your task is to generate a concise and descriptive title for the given chat history. The title should be no more than 5 words and should accurately reflect the main topic of the conversation.
"""

NAME_DATA_TABLE_SYSTEM_PROMPT = """
You are an expert at creating concise, descriptive titles. Your task is to generate a title for a data table that summarizes information extracted from research papers. The title should be no more than 10 words and should reflect both the papers' subject matter and the type of data being extracted. The title must be plaintext only — do not use any markdown formatting, asterisks, or special characters.
"""

NAME_DATA_TABLE_USER_MESSAGE = """
Generate a concise title (10 words or less) for a data table that extracts the following information from research papers.

Papers included:
{paper_titles}

Columns being extracted: {column_labels}

Title:
"""

RENAME_CONVERSATION_USER_MESSAGE = """
Given the following chat history, generate a new title for the conversation:

{chat_history}

New Title:
"""
