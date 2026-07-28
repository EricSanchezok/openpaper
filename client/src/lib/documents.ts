import type {
    DurableJob,
    PaperItem,
    PaperTag,
    PaperUploadJobStatusResponse,
} from "@/lib/schema";
import { fetchFromApi } from "@/lib/api";

export interface LibraryDocument {
    id: string;
    original_filename: string;
    mime_type: string;
    size_bytes: number;
    title: string | null;
    authors: string[] | null;
    abstract: string | null;
    institutions: string[] | null;
    keywords: string[] | null;
    doi: string | null;
    journal: string | null;
    publisher: string | null;
    publish_date: string | null;
    summary: string | null;
    summary_citations: Record<string, unknown>[] | null;
    starter_questions: string[] | null;
    processing_status: "pending" | "processing" | "completed" | "failed";
    parser_quality: "full" | "text_only" | null;
    parser_warning_code: string | null;
    created_at: string;
    updated_at: string;
}

export interface LibraryPaper {
    id: string;
    user_id: number;
    status: PaperItem["status"];
    last_accessed_at: string;
    metadata_overrides: Partial<
        Pick<
            LibraryDocument,
            | "title"
            | "authors"
            | "abstract"
            | "institutions"
            | "doi"
            | "journal"
            | "publisher"
            | "publish_date"
        >
    >;
    is_public: boolean;
    preview_url: string | null;
    tags: PaperTag[];
    document: LibraryDocument;
    created_at: string;
    updated_at: string;
}

export interface LibraryPaperList {
    items: LibraryPaper[];
}

export function libraryPaperToPaperItem(entry: LibraryPaper): PaperItem {
    const document = entry.document;
    const overrides = entry.metadata_overrides;
    return {
        id: document.id,
        library_paper_id: entry.id,
        title: overrides.title ?? document.title ?? document.original_filename,
        abstract: overrides.abstract ?? document.abstract ?? undefined,
        authors: overrides.authors ?? document.authors ?? undefined,
        institutions:
            overrides.institutions ?? document.institutions ?? undefined,
        summary: document.summary ?? undefined,
        created_at: entry.created_at,
        publish_date:
            overrides.publish_date ?? document.publish_date ?? undefined,
        status: entry.status,
        preview_url: entry.preview_url ?? undefined,
        size_in_kb: Math.ceil(document.size_bytes / 1024),
        tags: entry.tags,
        in_library: true,
        journal: overrides.journal ?? document.journal ?? undefined,
        doi: overrides.doi ?? document.doi ?? undefined,
        publisher: overrides.publisher ?? document.publisher ?? undefined,
        parser_quality: document.parser_quality,
        parser_warning_code: document.parser_warning_code,
    };
}

export async function fetchLibraryPapers(): Promise<PaperItem[]> {
    const response = await fetchFromApi(
        "/api/library/papers",
    ) as LibraryPaperList;
    return response.items
        .filter((entry) => entry.document.processing_status === "completed")
        .map(libraryPaperToPaperItem);
}

export async function fetchRelevantPapers(limit = 3): Promise<PaperItem[]> {
    const papers = await fetchLibraryPapers();
    const byRecency = (left: PaperItem, right: PaperItem) =>
        new Date(right.created_at ?? "").getTime()
        - new Date(left.created_at ?? "").getTime();
    const reading = papers
        .filter((paper) => paper.status === "reading")
        .sort(byRecency);
    const todo = papers.filter((paper) => paper.status === "todo").sort(byRecency);
    return [...reading, ...todo].slice(0, limit);
}

export async function fetchUploadJobStatus(
    jobId: string,
): Promise<PaperUploadJobStatusResponse> {
    const job = await fetchFromApi(`/api/jobs/${jobId}`) as DurableJob;
    return {
        job_id: job.id,
        status: job.status,
        title: null,
        started_at: job.started_at ?? job.created_at,
        created_at: job.created_at,
        completed_at: job.completed_at,
        paper_id: job.document_id,
        has_file_url: job.status === "completed",
        has_metadata: job.status === "completed",
        celery_progress_message: job.progress_message,
        parser_quality:
            job.result?.parser_quality === "full"
            || job.result?.parser_quality === "text_only"
                ? job.result.parser_quality
                : null,
        parser_warning_code:
            typeof job.result?.parser_warning_code === "string"
                ? job.result.parser_warning_code
                : null,
    };
}
