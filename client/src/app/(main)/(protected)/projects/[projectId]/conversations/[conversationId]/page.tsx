'use client';

import { useSubscription, isTokenCreditAtLimit } from '@/hooks/useSubscription';
import { fetchFromApi, fetchStreamFromApi } from '@/lib/api';
import { useState, useEffect, FormEvent, useRef, useCallback, useMemo, Suspense } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
    ChatMessage,
    CitationArtifact,
    ConversationDetail,
    ConversationMessagesResponse,
    MessageTrace,
    Reference,
} from '@/lib/schema';
import { useAuth } from '@/lib/auth';
import { useProjectWorkspace } from '@/components/project/ProjectWorkspaceProvider';
import { useProjects } from '@/hooks/useProjects';
import { PaperItem } from "@/lib/schema";
import { toast } from "sonner";
import { ConversationView } from '@/components/ConversationView';
import {
    EMPTY_PAPER_CONTEXT_SELECTION,
    EMPTY_TURN_ATTACHMENTS,
    PaperContextSelection,
    TurnAttachments,
    contextAndAttachmentsToScopeItems,
} from '@/components/chat/MentionAutocomplete';

interface ChatRequestBody {
    turn_id: string;
    user_query: string;
    mentioned_highlight_ids?: string[];
    reasoning_level: "standard" | "deep";
}

const chatLoadingMessages = [
    "Thinking about your question...",
    "Analyzing your knowledge base...",
    "Gathering citations...",
    "Double-checking references...",
    "Formulating a response...",
    "Verifying information...",
    "Crafting insights...",
    "Synthesizing findings...",
]

function ProjectConversationPageContent() {
    const router = useRouter();
    const params = useParams();
    const projectId = params.projectId as string;
    const conversationIdFromUrl = params.conversationId as string;

    const { user, loading: authLoading } = useAuth();
    // Shared workspace data + reader panel — papers open beside the chat.
    const {
        papers: projectPapers,
        project,
        isPapersLoading,
        conversations,
        openDocument,
        refreshPaperUrl,
        setCrumb,
        collapseArtifacts,
    } = useProjectWorkspace();
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [conversation, setConversation] = useState<ConversationDetail | null>(null);
    const [paperContextSelection, setPaperContextSelection] = useState<PaperContextSelection>({
        ...EMPTY_PAPER_CONTEXT_SELECTION,
        projectIds: [projectId],
    });
    const [turnAttachments, setTurnAttachments] = useState<TurnAttachments>(
        EMPTY_TURN_ATTACHMENTS,
    );
    const [libraryContext, setLibraryContext] = useState(false);
    const { projects } = useProjects();

    const papers = useMemo(
        () =>
            [...projectPapers].sort(
                (a: PaperItem, b: PaperItem) =>
                    new Date(b.created_at || "").getTime() -
                    new Date(a.created_at || "").getTime(),
            ),
        [projectPapers],
    );

    const [currentMessage, setCurrentMessage] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [conversationId, setConversationId] = useState<string | null>(conversationIdFromUrl);
    const [streamingChunks, setStreamingChunks] = useState<string[]>([]);
    const [streamingReferences, setStreamingReferences] = useState<Reference | undefined>(undefined);
    const [streamingArtifacts, setStreamingArtifacts] = useState<CitationArtifact[]>([]);
    const [currentLoadingMessageIndex, setCurrentLoadingMessageIndex] = useState(0);
    const [displayedText, setDisplayedText] = useState('');
    const [isTyping, setIsTyping] = useState(false);
    const [statusMessage, setStatusMessage] = useState('');
    const [highlightedInfo, setHighlightedInfo] = useState<{ documentId: string; messageIndex: number } | null>(null);
    const [isCentered, setIsCentered] = useState(false);
    const [isSessionLoading, setIsSessionLoading] = useState(true);
    const [reasoningLevel, setReasoningLevel] = useState<"standard" | "deep">("standard");

    const messagesEndRef = useRef<HTMLDivElement>(null);

    const END_DELIMITER = "END_OF_STREAM";

    const { subscription, refetch: refetchSubscription } = useSubscription();
    const tokenCreditLimitReached = isTokenCreditAtLimit(subscription);

    const conversationName = useMemo(
        () => conversations.find((c) => c.id === conversationIdFromUrl)?.title ?? '',
        [conversations, conversationIdFromUrl],
    );

    // Surface the conversation title in the workspace breadcrumb.
    useEffect(() => {
        setCrumb(conversationName || 'Chat');
        return () => setCrumb(null);
    }, [conversationName, setCrumb]);

    useEffect(() => {
        const TOKEN_CREDIT_TOAST_KEY = "token_credit_limit_toast_shown";
        if (tokenCreditLimitReached && !sessionStorage.getItem(TOKEN_CREDIT_TOAST_KEY)) {
            toast.error("You've used this week's Token Credits. Upgrade your plan to continue using AI features.", {
                action: {
                    label: "Upgrade",
                    onClick: () => window.location.href = "/pricing",
                },
            });
            sessionStorage.setItem(TOKEN_CREDIT_TOAST_KEY, "true");
        }
    }, [tokenCreditLimitReached]);

    const handleCitationClick = useCallback((key: string, messageIndex: number) => {
        setHighlightedInfo((prevHighlight) => {
            const message = messages[messageIndex];
            if (!message) return prevHighlight;

            const citation = message.references?.sources?.find(c => String(c.key) === key);
            if (!citation || citation.kind !== 'document') return prevHighlight;

            const newHighlight = { documentId: citation.document_id, messageIndex };

            // Scroll to element
            setTimeout(() => {
                const elementId = `${message.id || messageIndex}-reference-${citation.document_id}`;
                const element = document.getElementById(elementId);

                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }, 0);

            return newHighlight;
        });
    }, [messages]);


    const fetchMessages = useCallback(async (id: string) => {
        try {
            const [detail, response] = await Promise.all([
                fetchFromApi<ConversationDetail>(`/conversations/${id}`),
                fetchFromApi<ConversationMessagesResponse>(
                    `/conversations/${id}/messages?limit=100`,
                ),
            ]);
            if (response?.items) {
                setMessages(response.items);
                setConversation(detail);
                if (detail.paper_context.kind === 'selection') {
                    setLibraryContext(false);
                    setPaperContextSelection({
                        projectIds: detail.paper_context.project_ids,
                        documentIds: detail.paper_context.document_ids,
                    });
                } else {
                    setLibraryContext(true);
                    setPaperContextSelection(EMPTY_PAPER_CONTEXT_SELECTION);
                }
                setTurnAttachments(EMPTY_TURN_ATTACHMENTS);
                setConversationId(id);
                setIsCentered(false);
            }
        } catch (error) {
            console.error("Error fetching messages:", error);
            // Go back to the project page
            router.push(`/projects/${projectId}`);
            toast.error("Failed to load conversation history.");
        } finally {
            setIsSessionLoading(false);
        }
    }, [projectId, router]);

    useEffect(() => {
        if (!conversationIdFromUrl) {
            router.push(`/projects/${projectId}`);
            return;
        }

        if (user) {
            const pendingQuery = localStorage.getItem(`pending-query-${conversationIdFromUrl}`);
            if (pendingQuery) {
                // Apply the initial context selection carried over from the project page.
                const pendingPaperContextRaw = localStorage.getItem(
                    `pending-paper-context-${conversationIdFromUrl}`,
                );
                const pendingTurnAttachmentsRaw = localStorage.getItem(
                    `pending-turn-attachments-${conversationIdFromUrl}`,
                );
                // If mentions were carried over, wait for project papers to load so
                // their titles resolve — otherwise they persist as "Untitled paper".
                // Keep the localStorage keys until then; this effect re-runs when
                // isPapersLoading flips to false.
                if ((pendingPaperContextRaw || pendingTurnAttachmentsRaw) && isPapersLoading) {
                    return;
                }
                setIsSessionLoading(false);
                localStorage.removeItem(`pending-query-${conversationIdFromUrl}`);
                localStorage.removeItem(`pending-paper-context-${conversationIdFromUrl}`);
                localStorage.removeItem(`pending-turn-attachments-${conversationIdFromUrl}`);
                let pendingPaperContext: PaperContextSelection | undefined;
                let pendingTurnAttachments: TurnAttachments | undefined;
                if (pendingPaperContextRaw) {
                    try {
                        const selection = JSON.parse(
                            pendingPaperContextRaw,
                        ) as PaperContextSelection;
                        if (
                            Array.isArray(selection.documentIds)
                            && Array.isArray(selection.projectIds)
                        ) {
                            pendingPaperContext = selection;
                        }
                    } catch {
                        // Ignore malformed pending paper context.
                    }
                }
                if (pendingTurnAttachmentsRaw) {
                    try {
                        const attachments = JSON.parse(
                            pendingTurnAttachmentsRaw,
                        ) as TurnAttachments;
                        if (Array.isArray(attachments.highlights)) {
                            pendingTurnAttachments = attachments;
                        }
                    } catch {
                        // Ignore malformed pending turn attachments.
                    }
                }
                handleSubmit(
                    null,
                    pendingQuery,
                    pendingPaperContext,
                    pendingTurnAttachments,
                );
            } else if (messages.length === 0 && isSessionLoading && !isStreaming) {
                fetchMessages(conversationIdFromUrl);
            }
        } else if (!authLoading) {
            // Only clear messages if we're not loading auth and definitely have no user
            setMessages([]);
            setConversationId(null);
            setIsCentered(true);
            setIsSessionLoading(false);
        }
    }, [conversationIdFromUrl, user, fetchMessages, router, projectId, authLoading, isSessionLoading, isPapersLoading]);

    useEffect(() => {
        if (isStreaming) {
            setTimeout(() => {
                if (messagesEndRef.current) {
                    messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
                }
            }, 100);
        }
    }, [isStreaming]);

    useEffect(() => {
        if (!isStreaming) {
            setDisplayedText('');
            setIsTyping(false);
            return;
        }

        const currentMessage = chatLoadingMessages[currentLoadingMessageIndex];
        let charIndex = 0;
        setDisplayedText('');
        setIsTyping(true);

        const typingInterval = setInterval(() => {
            if (charIndex < currentMessage.length) {
                setDisplayedText(currentMessage.slice(0, charIndex + 1));
                charIndex++;
            } else {
                setIsTyping(false);
                clearInterval(typingInterval);
            }
        }, 50);

        return () => clearInterval(typingInterval);
    }, [isStreaming, currentLoadingMessageIndex]);

    useEffect(() => {
        if (!isStreaming) return;

        const messageInterval = setInterval(() => {
            setCurrentLoadingMessageIndex((prev) =>
                (prev + 1) % chatLoadingMessages.length
            );
        }, 11000);

        return () => clearInterval(messageInterval);
    }, [isStreaming]);

    useEffect(() => {
        if (isStreaming) {
            setCurrentLoadingMessageIndex(0);
        }
    }, [isStreaming]);

    const handleSubmit = useCallback(async (
        e: FormEvent | null = null,
        message?: string,
        paperContextOverride?: PaperContextSelection,
        turnAttachmentsOverride?: TurnAttachments,
    ) => {
        if (e) {
            e.preventDefault();
        }

        const query = message || currentMessage;

        if (
            !query.trim()
            || isStreaming
            || !conversationId
            || conversation?.capabilities.send === false
        ) return;

        // Get the artifacts panel out of the way so the reply is front-and-center.
        collapseArtifacts();

        // Paper/project context persists; highlights remain the only per-turn input.
        const submittedPaperContext = paperContextOverride ?? paperContextSelection;
        const submittedAttachments = turnAttachmentsOverride ?? turnAttachments;
        if (paperContextOverride) {
            setPaperContextSelection(submittedPaperContext);
        }
        if (turnAttachmentsOverride) {
            setTurnAttachments(submittedAttachments);
        }
        const userMessage: ChatMessage = {
            role: 'user',
            content: query,
            scope: [
                ...(libraryContext
                    ? [{ kind: 'library' as const, id: 'library', title: 'Library' }]
                    : []),
                ...contextAndAttachmentsToScopeItems(
                    submittedPaperContext,
                    submittedAttachments,
                    papers,
                    projects,
                ),
            ],
        };
        setMessages(prev => [...prev, userMessage]);
        setTurnAttachments(EMPTY_TURN_ATTACHMENTS);

        if (!message) {
            setCurrentMessage('');
        }

        setIsStreaming(true);
        setStreamingChunks([]);
        setStreamingReferences(undefined);
        setStreamingArtifacts([]);
        setError(null);

        const requestBody: ChatRequestBody = {
            turn_id: crypto.randomUUID(),
            user_query: query,
            reasoning_level: reasoningLevel,
        };
        if (submittedAttachments.highlights.length > 0) {
            requestBody.mentioned_highlight_ids = submittedAttachments.highlights.map(
                (highlight) => highlight.id,
            );
        }

        try {
            await fetchFromApi(`/conversations/${encodeURIComponent(conversationId)}/context`, {
                method: 'PUT',
                body: JSON.stringify(
                    libraryContext
                        ? { kind: 'library' }
                        : {
                            kind: 'selection',
                            project_ids: submittedPaperContext.projectIds,
                            document_ids: submittedPaperContext.documentIds,
                        },
                ),
            });
            const stream = await fetchStreamFromApi(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            }).catch(fetchError => {
                console.error('Fetch error details:', {
                    name: fetchError.name,
                    message: fetchError.message,
                    stack: fetchError.stack,
                    cause: fetchError.cause
                });
                throw fetchError;
            });

            if (!stream) {
                throw new Error('No stream received from server');
            }

            const reader = stream.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = '';
            let references: Reference | undefined = undefined;
            const artifacts: CitationArtifact[] = [];
            let trace: MessageTrace | undefined = undefined;
            let buffer = '';

            try {
                while (true) {
                    let result;
                    try {
                        result = await reader.read();
                    } catch (readerError) {
                        console.error('Stream reader error:', {
                            name: readerError instanceof Error ? readerError.name : 'Unknown',
                            message: readerError instanceof Error ? readerError.message : String(readerError),
                            stack: readerError instanceof Error ? readerError.stack : 'No stack',
                        });
                        throw readerError;
                    }

                    const { done, value } = result;

                    if (done) {
                        if (buffer.trim()) {
                            console.warn('Unprocessed buffer at end of stream:', buffer);
                        }
                        break;
                    }

                    if (!value) {
                        console.warn('Received empty value from stream');
                        continue;
                    }

                    let chunk;
                    try {
                        chunk = decoder.decode(value, { stream: true });
                    } catch (decodeError) {
                        console.error('Error decoding chunk:', decodeError);
                        console.error('Raw chunk value:', value);
                        continue;
                    }

                    buffer += chunk;

                    const parts = buffer.split(END_DELIMITER);
                    buffer = parts.pop() || '';

                    for (const event of parts) {
                        if (!event.trim()) continue;

                        try {
                            const parsedChunk = JSON.parse(event.trim());

                            if (parsedChunk && typeof parsedChunk === 'object' && 'type' in parsedChunk) {
                                const chunkType = parsedChunk.type;
                                const chunkContent = parsedChunk.content;

                                if (chunkType === 'content') {
                                    accumulatedContent += chunkContent;
                                    setStreamingChunks(prev => [...prev, chunkContent]);
                                } else if (chunkType === 'references') {
                                    references = chunkContent;
                                    setStreamingReferences(chunkContent);
                                } else if (chunkType === 'artifact') {
                                    artifacts.push(chunkContent as CitationArtifact);
                                    setStreamingArtifacts(prev => [...prev, chunkContent as CitationArtifact]);
                                } else if (chunkType === 'trace') {
                                    trace = chunkContent as MessageTrace;
                                } else if (chunkType === 'status') {
                                    setStatusMessage(chunkContent);
                                } else if (chunkType === 'error') {
                                    console.error('Server error in stream:', chunkContent);
                                    throw new Error(`Server error: ${chunkContent}`);
                                } else {
                                    console.warn(`Unknown chunk type: ${chunkType}`, parsedChunk);
                                }
                            } else if (parsedChunk) {
                                console.warn('Received unexpected chunk format:', parsedChunk);
                            }
                        } catch (parseError) {
                            console.error('Error parsing JSON event:', parseError);
                            console.error('Raw event that failed to parse:', JSON.stringify(event));
                            console.error('Event length:', event.length);
                            console.error('Event preview (first 200 chars):', event.substring(0, 200));
                            continue;
                        }
                    }
                }
            } finally {
                // Always release the reader
                try {
                    reader.releaseLock();
                } catch (lockError) {
                    console.warn('Error releasing reader lock:', lockError);
                }
            }

            if (accumulatedContent) {
                const finalMessage: ChatMessage = {
                    role: 'assistant',
                    content: accumulatedContent,
                    references: references,
                    artifacts: artifacts.length ? artifacts : undefined,
                    trace: trace,
                };
                setMessages(prev => {
                    const newMessages = [...prev, finalMessage];
                    return newMessages;
                });

                // Clear streaming state immediately after adding final message
                setStreamingChunks([]);
                setStreamingReferences(undefined);
                setStreamingArtifacts([]);
            }

        } catch (error) {
            console.error('Error during streaming:', error);

            // Enhanced error logging
            if (error instanceof Error) {
                console.error('Error details:', {
                    name: error.name,
                    message: error.message,
                    stack: error.stack,
                    cause: error.cause
                });
            }

            // Check for specific error types
            if (error instanceof TypeError) {
                if (error.message.includes('input stream') || error.message.includes('stream')) {
                    console.error('Stream-specific TypeError detected');
                    toast.error("Connection interrupted. Please try again.");
                } else if (error.message.includes('fetch')) {
                    console.error('Fetch-related TypeError detected');
                    toast.error("Network error: Please check your connection and try again.");
                } else {
                    console.error('Generic TypeError detected');
                    toast.error(`Type error: ${error.message}`);
                }
            } else if (error instanceof Error && error.name === 'AbortError') {
                console.error('Request was aborted');
                toast.error("Request was cancelled. Please try again.");
            } else if (error instanceof Error && error.message.includes('Server error:')) {
                // Server-sent error, don't wrap it
                toast.error(error.message);
            } else {
                // Generic error handling
                const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
                toast.error(`An error occurred: ${errorMessage}`);
            }

            setMessages(prev => prev.slice(0, -1));
            setCurrentMessage(query);
            setTurnAttachments(submittedAttachments);
            setError(`Streaming error: ${error instanceof Error ? error.message : 'Unknown error'}`);
        } finally {
            setIsStreaming(false);
            setStreamingChunks([]);
            setStreamingReferences(undefined);
            setStreamingArtifacts([]);
            setStatusMessage('');
            refetchSubscription();
        }
    }, [
        collapseArtifacts,
        conversation,
        conversationId,
        currentMessage,
        isStreaming,
        libraryContext,
        paperContextSelection,
        papers,
        project,
        projectId,
        projects,
        reasoningLevel,
        refetchSubscription,
        router,
        turnAttachments,
    ]);

    const [error, setError] = useState<string | null>(null);

    const handleRetry = useCallback(() => {
        setError(null);
        handleSubmit();
    }, [handleSubmit]);


    return (
        <div className="flex min-h-0 w-full flex-1 flex-col p-2">
            <div className="flex-1 min-h-0">
                <ConversationView
                    messages={messages}
                    canSend={conversation?.capabilities.send ?? true}
                    readOnlyReason={conversation?.read_only_reason}
                    papers={papers}
                    isStreaming={isStreaming}
                    streamingChunks={streamingChunks}
                    streamingReferences={streamingReferences}
                    streamingArtifacts={streamingArtifacts}
                    statusMessage={statusMessage}
                    error={error}
                    isSessionLoading={isSessionLoading}
                    tokenCreditLimitReached={tokenCreditLimitReached}
                    reasoningLevel={reasoningLevel}
                    onReasoningLevelChange={setReasoningLevel}
                    currentMessage={currentMessage}
                    onCurrentMessageChange={setCurrentMessage}
                    onSubmit={handleSubmit}
                    onRetry={handleRetry}
                    isCentered={isCentered}
                    setIsCentered={setIsCentered}
                    displayedText={displayedText}
                    isTyping={isTyping}
                    handleCitationClick={handleCitationClick}
                    highlightedInfo={highlightedInfo}
                    setHighlightedInfo={setHighlightedInfo}
                    authLoading={authLoading}
                    conversation={conversation}
                    onConversationChange={setConversation}
                    onRefreshPaperUrl={refreshPaperUrl}
                    onOpenDocumentExternal={openDocument}
                    paperContextSelection={paperContextSelection}
                    onPaperContextSelectionChange={(selection) => {
                        setLibraryContext(false);
                        setPaperContextSelection({
                            ...selection,
                            projectIds: Array.from(
                                new Set([projectId, ...selection.projectIds]),
                            ),
                        });
                    }}
                    turnAttachments={turnAttachments}
                    onTurnAttachmentsChange={setTurnAttachments}
                    libraryContext={libraryContext}
                    onLibraryContextChange={(selected) => {
                        setLibraryContext(selected);
                        if (selected) {
                            setPaperContextSelection(EMPTY_PAPER_CONTEXT_SELECTION);
                        } else {
                            setPaperContextSelection({
                                ...EMPTY_PAPER_CONTEXT_SELECTION,
                                projectIds: [projectId],
                            });
                        }
                    }}
                    projects={projects}
                    lockedProjectIds={libraryContext ? [] : [projectId]}
                />
            </div>
        </div>
    );
}

export default function ProjectConversationPage() {
    return (
        <Suspense fallback={<div>Loading...</div>}>
            <ProjectConversationPageContent />
        </Suspense>
    );
}
