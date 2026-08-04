import type { components } from "@/lib/api/generated/schema";

type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
type Conversation = components["schemas"]["ConversationSummaryResponse"];
type Message =
  components["schemas"]["app__modules__conversations__application__contracts__conversations__MessageResponse"];

const now = "2026-08-04T09:00:00Z";
const conversationCapabilities = {
  archive: true,
  delete: true,
  detach: false,
  move: true,
  pin: true,
  rename: true,
  send: true,
  share: false,
};

export const homeConversations: Conversation[] = [
  {
    id: "10000000-0000-4000-8000-000000000001",
    title: "Draft the related work",
    updated_at: now,
    scope_type: "project",
    scope_id: "20000000-0000-4000-8000-000000000001",
    scope_label: "Truthward",
    scope_access: "active",
    read_only: false,
    read_only_reason: null,
    pinned_at: now,
    archived_at: null,
    capabilities: conversationCapabilities,
  },
  {
    id: "10000000-0000-4000-8000-000000000002",
    title: "Summarize key findings",
    updated_at: "2026-08-03T09:00:00Z",
    scope_type: "paper",
    scope_id: "30000000-0000-4000-8000-000000000001",
    scope_label: "Attention paper",
    scope_access: "active",
    read_only: false,
    read_only_reason: null,
    pinned_at: "2026-08-03T09:00:00Z",
    archived_at: null,
    capabilities: conversationCapabilities,
  },
  ...[
    "Compare retrieval baselines",
    "What are the paper limitations?",
    "Plan the literature review",
  ].map((title, index): Conversation => ({
    id: `10000000-0000-4000-8000-00000000000${index + 3}`,
    title,
    updated_at: `2026-08-0${3 - index}T09:00:00Z`,
    scope_type: "global",
    scope_id: null,
    scope_label: index === 0 ? "Truthward" : null,
    scope_access: "active",
    read_only: false,
    read_only_reason: null,
    pinned_at: null,
    archived_at: null,
    capabilities: conversationCapabilities,
  })),
];

function paper(
  id: string,
  title: string,
  authors: string[],
  lastAccessedAt: string,
): LibraryPaper {
  return {
    library_entry_id: id.replace("30000000", "31000000"),
    user_id: 7,
    status: "reading",
    last_accessed_at: lastAccessedAt,
    metadata_overrides: {},
    is_public: false,
    preview_url: null,
    tags: [],
    document: {
      document_id: id,
      original_filename: `${title}.pdf`,
      mime_type: "application/pdf",
      size_bytes: 1_240_000,
      title,
      authors,
      abstract: null,
      institutions: null,
      keywords: null,
      doi: null,
      journal: null,
      publisher: null,
      publish_date: null,
      summary: null,
      summary_citations: null,
      starter_questions: null,
      processing_status: "completed",
      parser_quality: "high",
      parser_warning_code: null,
      created_at: now,
      updated_at: now,
    },
    created_at: now,
    updated_at: now,
  };
}

export const homePapers: LibraryPaper[] = [
  paper(
    "30000000-0000-4000-8000-000000000001",
    "Attention Is All You Need",
    ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
    "2026-08-04T07:00:00Z",
  ),
  paper(
    "30000000-0000-4000-8000-000000000002",
    "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    ["Patrick Lewis", "Ethan Perez"],
    "2026-08-03T07:00:00Z",
  ),
  paper(
    "30000000-0000-4000-8000-000000000003",
    "Constitutional AI: Harmlessness from AI Feedback",
    ["Yuntao Bai"],
    "2026-08-01T07:00:00Z",
  ),
];

function project(
  id: string,
  title: string,
  paperCount: number,
  updatedAt: string,
): Project {
  return {
    id,
    title,
    description: null,
    owner: { id: 7, display_name: "Eric", email: "eric@scholens.ai" },
    membership: {
      kind: "owner",
      permissions: {
        edit_project: true,
        manage_collaborators: true,
        manage_papers: true,
      },
    },
    capabilities: {
      read: true,
      contribute_research: true,
      create_conversation: true,
      edit_project: true,
      manage_papers: true,
      manage_collaborators: true,
      transfer: true,
      delete: true,
      leave: false,
    },
    num_papers: paperCount,
    num_conversations: Math.max(1, Math.floor(paperCount / 2)),
    num_collaborators: 2,
    num_audio_overviews: 0,
    num_data_tables: 0,
    created_at: now,
    updated_at: updatedAt,
  };
}

export const homeProjects: Project[] = [
  project(
    "20000000-0000-4000-8000-000000000001",
    "Thesis literature review",
    12,
    "2026-08-04T08:00:00Z",
  ),
  project(
    "20000000-0000-4000-8000-000000000002",
    "RAG evaluation",
    8,
    "2026-08-03T08:00:00Z",
  ),
  project(
    "20000000-0000-4000-8000-000000000003",
    "Reading queue",
    24,
    "2026-07-23T08:00:00Z",
  ),
];

export const homeMessages: Message[] = [
  {
    id: "40000000-0000-4000-8000-000000000001",
    role: "user",
    content: "What is the paper’s central contribution?",
    references: null,
    artifacts: null,
    trace: null,
    scope: null,
    sequence: 1,
  },
  {
    id: "40000000-0000-4000-8000-000000000002",
    role: "assistant",
    content:
      "The paper’s central contribution is a persistent runtime for agents that continue beyond a single interaction. It treats identity, collaboration, and accumulated experience as parts of the operating model—not add-ons to a chat session.",
    references: {
      annotations: [],
      sources: [
        {
          key: 1,
          kind: "document",
          document_id: homePapers[0]!.document.document_id,
          title: homePapers[0]!.document.title,
          authors: homePapers[0]!.document.authors ?? [],
          reference: "A persistent workspace connects collaborative sessions.",
          locator: { section: "Introduction" },
        },
      ],
    },
    artifacts: null,
    trace: {
      status_messages: [
        "Read the relevant passages",
        "Compared claims with evidence",
        "Grounded the response",
      ],
    },
    scope: null,
    sequence: 2,
  },
];
