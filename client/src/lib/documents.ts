import type {
    DurableJob,
    PaperData,
    PaperItem,
    PaperTag,
    PaperUploadJobStatusResponse,
    ReferenceCitation,
    SharedPaper,
} from "@/lib/schema";
import { fetchFromApi } from "@/lib/api";

export interface LibraryDocument {
    document_id: string;
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
    summary_citations: ReferenceCitation[] | null;
    starter_questions: string[] | null;
    processing_status: "pending" | "processing" | "completed" | "failed";
    parser_quality: "full" | "text_only" | null;
    parser_warning_code: string | null;
    created_at: string;
    updated_at: string;
}

export interface LibraryPaper {
    library_entry_id: string;
    user_id: number;
    status: NonNullable<PaperItem["status"]>;
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
    next_cursor: string | null;
}

interface DocumentFileUrlResponse {
    file_url: string;
}

interface PublicPaperResponse {
    document: LibraryDocument;
    file_url: string;
    owner: {
        id: number;
        display_name: string;
    };
}

function resolvedMetadata(entry: LibraryPaper) {
    return {
        title:
            entry.metadata_overrides.title
            ?? entry.document.title
            ?? entry.document.original_filename,
        authors:
            entry.metadata_overrides.authors ?? entry.document.authors ?? [],
        abstract:
            entry.metadata_overrides.abstract ?? entry.document.abstract ?? "",
        institutions:
            entry.metadata_overrides.institutions
            ?? entry.document.institutions
            ?? [],
        publish_date:
            entry.metadata_overrides.publish_date
            ?? entry.document.publish_date
            ?? "",
        journal:
            entry.metadata_overrides.journal ?? entry.document.journal ?? undefined,
        doi: entry.metadata_overrides.doi ?? entry.document.doi ?? undefined,
        publisher:
            entry.metadata_overrides.publisher
            ?? entry.document.publisher
            ?? undefined,
    };
}

export async function fetchLibraryPaperByDocument(
    documentId: string,
): Promise<LibraryPaper> {
    return await fetchFromApi(
        `/library/papers/${documentId}`,
    ) as LibraryPaper;
}

export async function fetchPaperData(documentId: string): Promise<PaperData> {
    const [entry, file] = await Promise.all([
        fetchLibraryPaperByDocument(documentId),
        fetchFromApi(
            `/papers/${documentId}/download-url`,
        ) as Promise<DocumentFileUrlResponse>,
    ]);
    const metadata = resolvedMetadata(entry);
    return {
        document_id: entry.document.document_id,
        filename: entry.document.original_filename,
        file_url: file.file_url,
        ...metadata,
        summary: entry.document.summary ?? "",
        summary_citations: entry.document.summary_citations ?? [],
        tags: entry.tags,
        starter_questions: entry.document.starter_questions ?? [],
        is_public: entry.is_public,
        share_id: null,
        status: entry.status,
        zotero_synced: false,
        parser_quality: entry.document.parser_quality,
        parser_warning_code: entry.document.parser_warning_code,
    };
}

export async function fetchPublicPaper(shareToken: string): Promise<SharedPaper> {
    const response = await fetchFromApi(
        `/shares/${encodeURIComponent(shareToken)}`,
    ) as PublicPaperResponse;
    const document = response.document;
    return {
        paper: {
            document_id: document.document_id,
            filename: document.original_filename,
            file_url: response.file_url,
            authors: document.authors ?? [],
            title: document.title ?? document.original_filename,
            abstract: document.abstract ?? "",
            publish_date: document.publish_date ?? "",
            summary: document.summary ?? "",
            summary_citations: document.summary_citations ?? [],
            institutions: document.institutions ?? [],
            starter_questions: document.starter_questions ?? [],
            is_public: true,
            share_id: shareToken,
            status: "reading",
            journal: document.journal ?? undefined,
            doi: document.doi ?? undefined,
            publisher: document.publisher ?? undefined,
            parser_quality: document.parser_quality,
            parser_warning_code: document.parser_warning_code,
        },
        owner: response.owner,
    };
}

export function libraryPaperToPaperItem(entry: LibraryPaper): PaperItem {
    const document = entry.document;
    const overrides = entry.metadata_overrides;
    return {
        id: document.document_id,
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
        "/library/papers",
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
    const job = await fetchFromApi(`/jobs/${jobId}`) as DurableJob;
    return {
        job_id: job.id,
        status: job.status,
        title: null,
        started_at: job.started_at ?? job.created_at,
        created_at: job.created_at,
        completed_at: job.completed_at,
        document_id: job.document_id,
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
