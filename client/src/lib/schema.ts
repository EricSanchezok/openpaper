import { PaperStatus } from "@/components/utils/PdfStatus";
import { BasicUser } from "./auth";

export type HighlightType = 'topic' | 'motivation' | 'method' | 'evidence' | 'result' | 'impact' | 'general';

export interface ReferenceCitation {
    index: number;
    text: string;
    paper_id?: string;
}

export interface PaperData {
    library_paper_id?: string;
    filename: string;
    file_url: string;
    authors: string[];
    title: string;
    abstract: string;
    publish_date: string;
    summary: string;
    summary_citations?: ReferenceCitation[];
    institutions: string[];
    tags?: PaperTag[];
    starter_questions: string[];
    is_public: boolean;
    share_id: string | null;
    status: PaperStatus;
    journal?: string;
    doi?: string;
    publisher?: string;
    zotero_synced?: boolean;
    parser_quality?: 'full' | 'text_only' | null;
    parser_warning_code?: string | null;
}

export interface SharedPaper {
    paper: PaperData;
    owner: BasicUser;
}

export interface CitationArtifactData {
    paper_id: string;
    title?: string;
    authors?: string[];
    publish_date?: string;
    journal?: string;
    publisher?: string;
    doi?: string;
}

export interface CitationArtifact {
    kind: 'citation';
    paper_id: string;
    preferred_style: string; // canonical key, e.g. "APA"
    style_display: string;
    data: CitationArtifactData;
    method: string;
    missing_fields: string[];
    confidence?: number | null;
}

export interface MessageTraceToolCall {
    name: string;
    args?: Record<string, unknown>;
}

export interface MessageTraceStep {
    kind: string;
    detail: string;
    data?: Record<string, unknown> | null;
}

export interface MessageTraceCitation {
    paper_id: string;
    method: string;
    preferred_style: string;
    steps: MessageTraceStep[];
}

export interface MessageTrace {
    // The live "thinking trace" — status messages shown during streaming.
    status_messages?: string[];
    reasoning_content?: string;
    tool_calls?: MessageTraceToolCall[];
    citations?: MessageTraceCitation[];
}

// Denormalized snapshot of an @-mention attached to a user message, frozen at
// send time so it renders even if the paper/project is later renamed/deleted.
export interface MessageScopeItem {
    kind: 'paper' | 'project' | 'highlight';
    id: string;
    title: string;
    // For highlight mentions: the parent paper, so the pill can link to it
    // and show the paper title on hover.
    paper_id?: string;
    paper_title?: string;
    // For highlight mentions: the annotations written on the highlight.
    annotations?: string[];
}

export interface ChatMessage {
    id?: string;
    role: 'user' | 'assistant';
    content: string;
    references?: Reference;
    // First-party artifacts (e.g. citations) produced for this turn. Set for
    // both freshly-streamed and persisted/reloaded messages.
    artifacts?: CitationArtifact[];
    // Agent trajectory (tool calls + per-citation subagent steps) for this turn.
    trace?: MessageTrace;
    // @-mention context attached to this (user) turn.
    scope?: MessageScopeItem[];
}

// Position types for react-pdf-highlighter-extended
export interface ScaledRect {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    width: number;
    height: number;
    pageNumber: number;
}

export interface ScaledPosition {
    boundingRect: ScaledRect;
    rects: ScaledRect[];
    usePdfCoordinates?: boolean;
}

export type HighlightColor = 'yellow' | 'green' | 'blue' | 'pink' | 'purple';

export interface ResearchCreator {
    id: number | null;
    display_name: string | null;
}

export interface ResearchItemCapabilities {
    share: boolean;
    edit: boolean;
    delete: boolean;
}

export interface ResearchComment {
    id: string;
    thread_id: string;
    content: string;
    role: 'user' | 'assistant';
    created_by: ResearchCreator;
    created_at: string;
    updated_at: string;
    can_edit: boolean;
    can_delete: boolean;
}

export interface ResearchItem {
    id: string;
    kind: 'highlight_thread' | 'citation' | 'audio_overview' | 'data_table';
    scope_type: 'personal' | 'document' | 'project';
    scope_id: string | null;
    is_shared: boolean;
    created_by: ResearchCreator;
    created_at: string;
    updated_at: string;
    capabilities: ResearchItemCapabilities;
    citation: {
        snapshot: Record<string, unknown>;
    } | null;
    audio_overview: {
        title: string | null;
        transcript: string;
        citations: Record<string, unknown>[];
        audio_url: string;
        voice_id: string;
        model_version: string;
    } | null;
    data_table: {
        title: string | null;
        columns: string[];
        rows: Record<string, unknown>[];
        citations: Record<string, unknown>[];
        row_failures: string[];
    } | null;
    highlight_thread: {
        quote_text: string;
        page_number: number | null;
        start_offset: number | null;
        end_offset: number | null;
        position: Record<string, unknown> | null;
        color: string;
        role: string;
        comments: ResearchComment[];
    } | null;
}

export interface DurableJob {
    id: string;
    operation: string;
    document_id: string | null;
    project_id: string | null;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
    progress_message: string | null;
    error_code: string | null;
    result: Record<string, unknown> | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
}

export interface PaperHighlight {
    id?: string;
    raw_text: string;
    role: 'user' | 'assistant';
    start_offset?: number;
    end_offset?: number;
    page_number?: number;
    type?: HighlightType;
    position?: ScaledPosition;
    color?: HighlightColor;
    project_id?: string | null;
    is_shared?: boolean;
    created_by?: ResearchCreator | null;
}

export interface PaperHighlightAnnotation {
    id: string;
    highlight_id: string;
    paper_id: string;
    content: string;
    role: 'user' | 'assistant';
    created_at: string;
    created_by?: ResearchCreator | null;
}

export interface Reference {
    citations: Citation[];
}

export interface Citation {
    key: string;
    paper_id?: string;
    reference: string;
}

export interface Conversation {
    id: string;
    title: string;
    updated_at: string;
    scope_type: 'global' | 'project' | 'paper';
    scope_id: string | null;
    scope_label: string | null;
    scope_access: 'active' | 'lost';
    read_only: boolean;
    read_only_reason: 'scope_access_lost' | 'project_deleted' | 'document_deleted' | null;
    pinned_at: string | null;
    archived_at: string | null;
    capabilities: {
        rename: boolean;
        pin: boolean;
        move: boolean;
        detach: boolean;
        archive: boolean;
        share: false;
        delete: boolean;
        send: boolean;
    };
}

export interface ConversationListResponse {
    items: Conversation[];
    next_cursor: string | null;
}


export interface OpenAlexPaper {
    id: string
    title: string
    doi?: string
    publication_year: number
    publication_date: string
    open_access?: {
        is_oa: boolean
        oa_status: string
        oa_url?: string
    }
    keywords?: Array<{
        display_name: string
        score?: number
    }>
    primary_location?: {
        is_oa: boolean
        landing_page_url: string
        pdf_url?: string
        source?: {
            id: string
            display_name: string
            type?: string
            host_organization?: string
        }
    }
    biblio?: {
        volume?: string
        issue?: string
        first_page?: string
        last_page?: string
    }
    authorships?: Array<{
        author?: {
            id: string
            orcid?: string
            display_name?: string
        }
        institutions?: {
            id: string
            type: string
            display_name: string
            ror?: string
        }[]
    }>
    topics?: Array<{
        display_name: string
        score?: number,
        subfield: {
            display_name: string
        },
        field: {
            display_name: string
        },
        domain: {
            display_name: string
        }
    }>
    cited_by_count?: number
    abstract?: string
}

export interface OpenAlexResponse {
    meta: {
        count: number
        page: number | null
        per_page: number
    },
    results: Array<OpenAlexPaper>
}

export interface OpenAlexMatchResponse {
    center: OpenAlexPaper;
    cites: OpenAlexResponse;
    cited_by: OpenAlexResponse;
}

export const JobStatus = {
    PENDING: 'pending',
    RUNNING: 'running',
    COMPLETED: 'completed',
    FAILED: 'failed',
    CANCELLED: 'cancelled',
} as const;

export type JobStatus = (typeof JobStatus)[keyof typeof JobStatus];

export const SubscriptionStatus = {
    ACTIVE: 'active',
    CANCELED: 'canceled',
    PAST_DUE: 'past_due',
    INCOMPLETE: 'incomplete',
    TRIALING: 'trialing',
    UNPAID: 'unpaid',
} as const;

export type SubscriptionStatus = (typeof SubscriptionStatus)[keyof typeof SubscriptionStatus];

export interface UserSubscription {
    has_subscription: boolean;
    had_subscription: boolean;
    requires_payment_update: boolean;
    subscription: {
        status: SubscriptionStatus;
        interval: "month" | "year";
        current_period_end: string;
        current_period_start: string;
        cancel_at_period_end: boolean;
    };
    scheduled_change?: {
        new_interval: "month" | "year";
        effective_date: string;
    } | null;
}

export interface HighlightResult {
    id: string;
    raw_text: string;
    start_offset: number | null;
    end_offset: number | null;
    page_number: number | null;
    role: string;
    created_at: string;
    type?: HighlightType;
}

export interface AnnotationResult {
    id: string;
    content: string;
    role: string;
    created_at: string;
    highlight: HighlightResult;
}

export interface PaperResult {
    id: string;
    title: string | null;
    authors: string[] | null;
    abstract: string | null;
    status: string;
    publish_date: string | null;
    created_at: string;
    last_accessed_at: string;
    highlights: HighlightResult[];
    annotations: AnnotationResult[];
    preview_url: string | null;
}

export interface SearchResults {
    papers: PaperResult[];
    total_papers: number;
    total_highlights: number;
    total_annotations: number;
}

export interface JobStatusResponse {
    job_id: string;
    status: JobStatus;
    title: string | null;
    started_at: string;
    created_at: string;
    completed_at: string | null;
}

export interface PaperUploadJobStatusResponse extends JobStatusResponse {
    paper_id: string | null;
    has_file_url: boolean;
    has_metadata: boolean;
    celery_progress_message: string | null;
    parser_quality: 'full' | 'text_only' | null;
    parser_warning_code: string | null;
}

export interface PaperTag {
    id: string;
    name: string;
    color: string;
}

export interface PaperItem {
    id: string
    library_paper_id?: string
    title: string
    abstract?: string
    authors?: string[]
    institutions?: string[]
    summary?: string
    created_at?: string
    publish_date?: string
    status?: PaperStatus
    preview_url?: string
    file_url?: string
    size_in_kb?: number
    tags?: PaperTag[]
    in_library?: boolean
    journal?: string
    doi?: string
    publisher?: string
    parser_quality?: 'full' | 'text_only' | null
    parser_warning_code?: string | null
}

export interface CreditUsage {
    used: number;
    remaining: number;
    total: number;
    usagePercentage: number;
    showWarning: boolean;
    isNearLimit: boolean;
    isCritical: boolean;
}

export interface Project {
    id: string;
    title: string;
    description: string;
    num_papers?: number;
    num_conversations?: number;
    num_audio_overviews?: number;
    num_data_tables?: number;
    created_at: string;
    updated_at: string;
    num_collaborators?: number;
    owner: ProjectOwner;
    membership: ProjectMembership;
    capabilities: ProjectCapabilities;
}

export interface PdfUploadResponse {
    message: string;
    job_id: string;
    file_name?: string;
}

export interface MinimalJob {
    jobId: string;
    fileName: string;
}

export interface ProjectPermissions {
    edit_project: boolean;
    manage_papers: boolean;
    manage_collaborators: boolean;
}

export interface ProjectOwner {
    id: number;
    display_name: string;
    email: string;
}

export interface ProjectMembership {
    kind: 'owner' | 'collaborator';
    permissions: ProjectPermissions;
}

export interface ProjectCapabilities {
    read: boolean;
    edit_project: boolean;
    manage_papers: boolean;
    manage_collaborators: boolean;
    create_conversation: boolean;
    contribute_research: boolean;
    transfer: boolean;
    delete: boolean;
    leave: boolean;
}

export interface Collaborator {
    user_id: number;
    display_name: string;
    email: string;
    is_owner: boolean;
    permissions: ProjectPermissions;
    joined_at: string | null;
}

export interface PendingInvite {
    id?: string;
    email: string;
    permissions: ProjectPermissions;
    expires_at?: string;
}

export interface ProjectInvitation {
    id: string;
    project_id: string;
    project_name: string;
    invited_by: string;
    email: string;
    permissions: ProjectPermissions;
    expires_at: string;
    created_at: string;
}

export interface SubscriptionLimits {
    paper_uploads: number;
    knowledge_base_size: number;
    token_credits_weekly: number;
    projects: number;
    project_papers: number;
}

export interface SubscriptionUsage {
    paper_uploads: number;
    paper_uploads_remaining: number;
    knowledge_base_size: number;
    knowledge_base_size_remaining: number;
    token_credits_weekly: number;
    token_credits_used: number;
    token_credits_remaining: number;
    token_credits_overage: number;
    projects: number;
    projects_remaining: number;
}

export interface SubscriptionData {
    plan: 'basic' | 'researcher';
    limits: SubscriptionLimits;
    usage: SubscriptionUsage;
}

export interface UseSubscriptionReturn {
    subscription: SubscriptionData | null;
    loading: boolean;
    error: string | null;
    refetch: () => Promise<void>;
}
