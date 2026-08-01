"use client";

import { reportClientIssue } from "@/lib/client-observability";
import { useState, useEffect, useCallback } from "react";
import { fetchFromApi } from "@/lib/api";
import { Project, PaperItem, ConversationSummary, ConversationListResponse, ProjectListResponse } from "@/lib/schema";

interface UseProjectsResult {
    projects: Project[];
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
}

export function useProjects(): UseProjectsResult {
    const [projects, setProjects] = useState<Project[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    const fetchProjects = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetchFromApi<ProjectListResponse>("/projects");
            setProjects(response.items);
        } catch (err) {
            setError(err instanceof Error ? err : new Error("Failed to fetch projects"));
            reportClientIssue("Error fetching projects:", err);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchProjects();
    }, []);

    return {
        projects,
        isLoading,
        error,
        refetch: fetchProjects,
    };
}

interface UseProjectResult {
    project: Project | null;
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
}

export function useProject(projectId?: string): UseProjectResult {
    const [project, setProject] = useState<Project | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    const fetchProject = async () => {
        if (!projectId) {
            setProject(null);
            setIsLoading(false);
            return;
        }
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetchFromApi<Project>(`/projects/${projectId}`);
            setProject(response);
        } catch (err) {
            setError(err instanceof Error ? err : new Error(`Failed to fetch project ${projectId}`));
            reportClientIssue(`Error fetching project ${projectId}:`, err);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchProject();
    }, [projectId]);

    return {
        project,
        isLoading,
        error,
        refetch: fetchProject,
    };
}

interface UseProjectPapersOptions {
    // Whether the list endpoint should also generate presigned file URLs.
    // Defaults to false — most consumers only need paper metadata, and URL
    // generation is expensive. Consumers that need a URL for a single paper
    // should fetch it lazily via getProjectPaperFileUrl instead.
    loadUrls?: boolean;
}

interface UseProjectPapersResult {
    papers: PaperItem[];
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
    // Locally patch a single paper (e.g. to inject a refreshed file_url)
    // without refetching the whole list.
    updatePaper: (documentId: string, patch: Partial<PaperItem>) => void;
}

export function useProjectPapers(
    projectId?: string,
    options?: UseProjectPapersOptions,
): UseProjectPapersResult {
    const loadUrls = options?.loadUrls ?? false;
    const [papers, setPapers] = useState<PaperItem[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    const fetchPapers = useCallback(async () => {
        if (!projectId) {
            setPapers([]);
            setIsLoading(false);
            return;
        }
        setIsLoading(true);
        setError(null);
        try {
            const query = loadUrls ? "?load_urls=true" : "";
            const response = await fetchFromApi<{
                items: PaperItem[];
                next_cursor: string | null;
            }>(`/projects/${projectId}/papers${query}`);
            setPapers(response.items);
        } catch (err) {
            setError(err instanceof Error ? err : new Error(`Failed to fetch papers for project ${projectId}`));
            reportClientIssue(`Error fetching papers for project ${projectId}:`, err);
        } finally {
            setIsLoading(false);
        }
    }, [projectId, loadUrls]);

    useEffect(() => {
        fetchPapers();
    }, [fetchPapers]);

    const updatePaper = useCallback((documentId: string, patch: Partial<PaperItem>) => {
        setPapers(prev => prev.map(p => (p.document_id === documentId ? { ...p, ...patch } : p)));
    }, []);

    return {
        papers,
        isLoading,
        error,
        refetch: fetchPapers,
        updatePaper,
    };
}

interface UseProjectConversationsResult {
    conversations: ConversationSummary[];
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
}

export function useProjectConversations(projectId?: string): UseProjectConversationsResult {
    const [conversations, setConversations] = useState<ConversationSummary[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);

    const fetchConversations = useCallback(async () => {
        if (!projectId) {
            setConversations([]);
            setIsLoading(false);
            return;
        }
        setIsLoading(true);
        setError(null);
        try {
            const response = await fetchFromApi(
                "/conversations?limit=100",
            ) as ConversationListResponse;
            setConversations(
                response.items.filter(
                    (conversation) =>
                        conversation.scope_type === "project"
                        && conversation.scope_id === projectId,
                ),
            );
        } catch (err) {
            setError(err instanceof Error ? err : new Error(`Failed to fetch conversations for project ${projectId}`));
            reportClientIssue(`Error fetching conversations for project ${projectId}:`, err);
        } finally {
            setIsLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchConversations();
    }, [fetchConversations]);

    return {
        conversations,
        isLoading,
        error,
        refetch: fetchConversations,
    };
}
