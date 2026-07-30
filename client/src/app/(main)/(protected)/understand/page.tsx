
'use client';

import { useSubscription, isTokenCreditAtLimit } from '@/hooks/useSubscription';
import { fetchFromApi, fetchStreamFromApi, getPaperFileUrl } from '@/lib/api';
import { useState, useEffect, FormEvent, useRef, useCallback, Suspense, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePapers } from '@/hooks/usePapers';
import { useProjects } from '@/hooks/useProjects';
import {
    EMPTY_PAPER_CONTEXT_SELECTION,
    EMPTY_TURN_ATTACHMENTS,
    PaperContextSelection,
    TurnAttachments,
    contextAndAttachmentsToScopeItems,
} from '@/components/chat/MentionAutocomplete';

import { toast } from "sonner";

import {
    ChatMessage,
    CitationArtifact,
    ConversationDetail,
    ConversationMessagesResponse,
    MessageTrace,
    Reference,
} from '@/lib/schema';
import { useAuth } from '@/lib/auth';

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

import { ConversationView } from "@/components/ConversationView";

function UnderstandPageContent() {
    const searchParams = useSearchParams();
    const { user, loading: authLoading } = useAuth();
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    // Paper metadata only — file URLs are fetched lazily per-paper on demand
    // (via refreshPaperUrl) when a citation/reference is opened.
    const { papers: fetchedPapers, isLoading: isPapersLoading, error: papersError } = usePapers();
    const { projects } = useProjects();
    const [paperContextSelection, setPaperContextSelection] =
        useState<PaperContextSelection>(EMPTY_PAPER_CONTEXT_SELECTION);
    const [turnAttachments, setTurnAttachments] =
        useState<TurnAttachments>(EMPTY_TURN_ATTACHMENTS);
    const [libraryContext, setLibraryContext] = useState(true);

    const papers = useMemo(() => {
        if (!fetchedPapers) return [];
        return [...fetchedPapers].sort((a, b) => {
            return new Date(b.created_at || "").getTime() - new Date(a.created_at || "").getTime();
        });
    }, [fetchedPapers]);

    useEffect(() => {
        if (papersError) {
            console.error("Error fetching papers:", papersError);
            toast.error("Failed to fetch papers.");
        }
    }, [papersError]);


    const messagesContainerRef = useRef<HTMLDivElement>(null);
    const [currentMessage, setCurrentMessage] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [conversationId, setConversationId] = useState<string | null>(null);
    const [conversation, setConversation] = useState<ConversationDetail | null>(null);
    const [streamingChunks, setStreamingChunks] = useState<string[]>([]);
    const [streamingReferences, setStreamingReferences] = useState<Reference | undefined>(undefined);
    const [streamingArtifacts, setStreamingArtifacts] = useState<CitationArtifact[]>([]);
    const [currentLoadingMessageIndex, setCurrentLoadingMessageIndex] = useState(0);
    const [displayedText, setDisplayedText] = useState('');
    const [isTyping, setIsTyping] = useState(false);
    const [statusMessage, setStatusMessage] = useState('');

    const [isSessionLoading, setIsSessionLoading] = useState(true);
    const [reasoningLevel, setReasoningLevel] = useState<"standard" | "deep">("standard");

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputMessageRef = useRef<HTMLTextAreaElement>(null);

    const END_DELIMITER = "END_OF_STREAM";

    const { subscription, refetch: refetchSubscription } = useSubscription();
    const tokenCreditLimitReached = isTokenCreditAtLimit(subscription);

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

    const [highlightedInfo, setHighlightedInfo] = useState<{ documentId: string; messageIndex: number } | null>(null);

    const handleCitationClick = useCallback((key: string, messageIndex: number) => {
        const message = messages[messageIndex];
        if (!message) return;

        const citation = message.references?.citations?.find(c => String(c.key) === key);
        if (!citation || !citation.document_id) return;

        setHighlightedInfo({ documentId: citation.document_id, messageIndex });

        const elementId = message.id ? `${message.id}-reference-paper-card-${citation.document_id}` : `${messageIndex}-reference-paper-card-${citation.document_id}`;
        const element = document.getElementById(elementId);

        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
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
                setMessages(response.items);
                setConversationId(id);
                setIsCentered(false);
            }
        } catch (error) {
            console.error("Error fetching messages:", error);
            toast.error("Failed to load conversation history.");
        } finally {
            setIsSessionLoading(false); // New line
        }
    }, []);

    // We don't want to refetch the conversation history or reset the chat state
    // while an answer is being streamed, as this can cause jarring UI updates
    // (e.g., showing the loading skeleton unnecessarily).
    useEffect(() => {
        const id = searchParams.get('id');
        const queryParam = searchParams.get('q');

        if (id && user && !isStreaming) {
            fetchMessages(id);
        } else if (!id && !isStreaming) {
            setMessages([]);
            setConversationId(null);
            setConversation(null);
            setIsCentered(true);
            setIsSessionLoading(false);

            // Pre-fill the input with the query parameter if provided
            if (queryParam && !currentMessage) {
                setCurrentMessage(queryParam);
                // Focus the input after a short delay
                setTimeout(() => {
                    inputMessageRef.current?.focus();
                }, 100);
            }
        }
    }, [searchParams, user, fetchMessages, isStreaming]);

    useEffect(() => {
        if (isStreaming) {
            setTimeout(() => {
                scrollToBottom();
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

    const scrollToBottom = () => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        } else if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
        }
    };

    const handleSubmit = useCallback(async (e: FormEvent | null = null) => {
        if (e) {
            e.preventDefault();
        }

        if (
            !currentMessage.trim()
            || isStreaming
            || (conversation && !conversation.capabilities.send)
        ) return;

        // Highlights are per-turn attachments; paper/project context persists.
        const submittedPaperContext = paperContextSelection;
        const submittedAttachments = turnAttachments;
        const userMessage: ChatMessage = {
            role: 'user',
            content: currentMessage,
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
        setCurrentMessage('');
        setTurnAttachments(EMPTY_TURN_ATTACHMENTS);

        setIsStreaming(true);
        setStreamingChunks([]);
        setStreamingReferences(undefined);
        setStreamingArtifacts([]);
        setError(null);

        let currentConversationId = conversationId;

        if (!currentConversationId) {
            try {
                const newConversationResponse = await fetchFromApi<ConversationDetail>('/conversations', {
                    method: 'POST',
                    body: JSON.stringify({
                        scope_type: 'global',
                        paper_context: libraryContext
                            ? { kind: 'library' }
                            : {
                                kind: 'selection',
                                project_ids: submittedPaperContext.projectIds,
                                document_ids: submittedPaperContext.documentIds,
                            },
                    }),
                });
                currentConversationId = newConversationResponse.id;
                setConversationId(currentConversationId);
                setConversation(newConversationResponse);
                window.history.pushState(null, '', `/understand?id=${currentConversationId}`);
            } catch (error) {
                console.error('Error creating conversation:', error);
                toast.error("Failed to start a new conversation.");
                setMessages(prev => prev.slice(0, -1));
                setCurrentMessage(userMessage.content);
                setTurnAttachments(submittedAttachments);
                setIsStreaming(false);
                setError('Failed to start a new conversation.');
                return;
            }
        }
        if (!currentConversationId) {
            return;
        }

        const requestBody: ChatRequestBody = {
            turn_id: crypto.randomUUID(),
            user_query: userMessage.content,
            reasoning_level: reasoningLevel,
        };
        if (submittedAttachments.highlights.length > 0) {
            requestBody.mentioned_highlight_ids = submittedAttachments.highlights.map(
                (h) => h.id,
            );
        }

        try {
            if (conversationId) {
                await fetchFromApi(`/conversations/${encodeURIComponent(currentConversationId)}/context`, {
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
            }
            const stream = await fetchStreamFromApi(`/conversations/${encodeURIComponent(currentConversationId)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            });

            const reader = stream.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = '';
            let references: Reference | undefined = undefined;
            const artifacts: CitationArtifact[] = [];
            let trace: MessageTrace | undefined = undefined;
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) {
                    if (buffer.trim()) {
                        console.warn('Unprocessed buffer at end of stream:', buffer);
                    }
                    break;
                }

                const chunk = decoder.decode(value, { stream: true });
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
                                console.warn(`Unknown chunk type: ${chunkType}`);
                            }
                        } else if (parsedChunk) {
                            console.warn('Received unexpected chunk:', parsedChunk);
                        }
                    } catch (error) {
                        if (error instanceof Error) {
                            throw error;
                        }
                        console.error('Error processing event:', error, 'Raw event:', event);
                        continue;
                    }
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
                setMessages(prev => [...prev, finalMessage]);
            }

        } catch (error) {
            console.error('Error during streaming:', error);
            toast.error("An error occurred while processing your request.");
            setMessages(prev => prev.slice(0, -1));
            setCurrentMessage(userMessage.content);
            setTurnAttachments(submittedAttachments);
            setError('An error occurred while processing your request.');
        } finally {
            setIsStreaming(false);
            setStatusMessage('');
            refetchSubscription();
        }
    }, [
        conversation,
        conversationId,
        currentMessage,
        isStreaming,
        libraryContext,
        paperContextSelection,
        papers,
        projects,
        reasoningLevel,
        turnAttachments,
    ]);

    const [error, setError] = useState<string | null>(null);

    const handleRetry = useCallback(() => {
        setError(null);
        handleSubmit();
    }, [handleSubmit]);

    useEffect(() => {
        const focusInput = () => {
            if (inputMessageRef.current &&
                !isStreaming &&
                papers.length > 0 &&
                !tokenCreditLimitReached) {
                // Small delay to ensure DOM is ready
                setTimeout(() => {
                    inputMessageRef.current?.focus();
                }, 100);
            }
        };

        focusInput();
    }, [papers.length, isStreaming, tokenCreditLimitReached]); // Dependencies that affect focusability

    const [isCentered, setIsCentered] = useState(true);

    const refreshPaperUrl = useCallback(async (documentId: string): Promise<string | null> => {
        try {
            return await getPaperFileUrl(documentId);
        } catch (error) {
            console.error('Error refreshing paper URL:', error);
            return null;
        }
    }, []);

    return (
        <div className="h-[calc(100vh-64px)] mx-2">
            <ConversationView
                messages={messages}
                canSend={!conversation || conversation.capabilities.send}
                readOnlyReason={conversation?.read_only_reason}
                papers={papers}
                isStreaming={isStreaming}
                streamingChunks={streamingChunks}
                streamingReferences={streamingReferences}
                streamingArtifacts={streamingArtifacts}
                isPapersLoading={isPapersLoading}
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
                onRefreshPaperUrl={refreshPaperUrl}
                projects={projects}
                paperContextSelection={paperContextSelection}
                onPaperContextSelectionChange={(selection) => {
                    const hasExplicitContext =
                        selection.documentIds.length > 0
                        || selection.projectIds.length > 0;
                    if (hasExplicitContext) {
                        setLibraryContext(false);
                    } else {
                        setLibraryContext(true);
                    }
                    setPaperContextSelection(selection);
                }}
                turnAttachments={turnAttachments}
                onTurnAttachmentsChange={setTurnAttachments}
                libraryContext={libraryContext}
                onLibraryContextChange={(selected) => {
                    setLibraryContext(selected);
                    if (selected) {
                        setPaperContextSelection(EMPTY_PAPER_CONTEXT_SELECTION);
                    }
                }}
            />
        </div>
    );
}

export default function UnderstandPage() {
    return (
        <Suspense fallback={<div>Loading...</div>}>
            <UnderstandPageContent />
        </Suspense>
    );
}
