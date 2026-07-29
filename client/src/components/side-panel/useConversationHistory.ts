import { useCallback, useEffect, useRef, useState } from "react";

import { fetchFromApi } from "@/lib/api";
import type { ChatMessage, Conversation } from "@/lib/schema";

interface ConversationListResponse {
	items: Conversation[];
}

interface MessagePageResponse {
	items: ChatMessage[];
	next_cursor: string | null;
}

interface UseConversationHistoryOptions {
	documentId: string;
	enabled: boolean;
	initialConversationId?: string | null;
}

export function useConversationHistory({
	documentId,
	enabled,
	initialConversationId,
}: UseConversationHistoryOptions) {
	const [conversationId, setConversationId] = useState<string | null>(null);
	const [conversation, setConversation] = useState<Conversation | null>(null);
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const [hasMoreMessages, setHasMoreMessages] = useState(true);
	const [isLoadingMoreMessages, setIsLoadingMoreMessages] = useState(false);
	const [isFetchingHistory, setIsFetchingHistory] = useState(true);
	const [messageCursor, setMessageCursor] = useState<string | null>(null);
	const messagesContainerRef = useRef<HTMLDivElement | null>(null);

	const fetchMoreMessages = useCallback(async () => {
		if (!conversationId || !hasMoreMessages || isLoadingMoreMessages) {
			if (!isLoadingMoreMessages && isFetchingHistory) {
				setIsFetchingHistory(false);
			}
			return;
		}

		setIsLoadingMoreMessages(true);
		try {
			const cursorQuery = messageCursor
				? `&cursor=${encodeURIComponent(messageCursor)}`
				: "";
			const response = (await fetchFromApi(
				`/conversations/${conversationId}/messages?limit=50${cursorQuery}`,
				{ method: "GET" },
			)) as MessagePageResponse;
			const fetchedMessages = response.items.map((message) => ({
				role: message.role,
				content: message.content,
				id: message.id,
				references: message.references,
			}));
			if (fetchedMessages.length === 0) {
				setHasMoreMessages(false);
				return;
			}

			const container = messagesContainerRef.current;
			const previousHeight = container?.scrollHeight ?? 0;
			setMessages((previous) => [...fetchedMessages, ...previous]);
			setMessageCursor(response.next_cursor);
			setHasMoreMessages(response.next_cursor !== null);
			requestAnimationFrame(() => {
				if (container) {
					container.scrollTop = container.scrollHeight - previousHeight;
				}
			});
		} finally {
			setIsLoadingMoreMessages(false);
			setIsFetchingHistory(false);
		}
	}, [
		conversationId,
		hasMoreMessages,
		isFetchingHistory,
		isLoadingMoreMessages,
		messageCursor,
	]);

	useEffect(() => {
		if (!enabled || !documentId) return;

		setMessages([]);
		setMessageCursor(null);
		setHasMoreMessages(true);
		setIsFetchingHistory(true);
		let cancelled = false;
		async function loadConversation() {
			try {
				let id: string | null = initialConversationId ?? null;
				if (id) {
					const detail = await fetchFromApi(
						`/conversations/${id}`,
					) as Conversation;
					if (!cancelled) {
						setConversationId(id);
						setConversation(detail);
					}
					return;
				}
				const existing = (await fetchFromApi(
					"/conversations?limit=100",
					{ method: "GET" },
				)) as ConversationListResponse;
				id = existing.items.find(
					(conversation) =>
						conversation.scope_type === "paper"
						&& conversation.scope_id === documentId,
				)?.id ?? null;
				if (id) {
					const detail = await fetchFromApi(
						`/conversations/${id}`,
					) as Conversation;
					if (!cancelled) {
						setConversationId(id);
						setConversation(detail);
					}
					return;
				}
				try {
					const created = (await fetchFromApi(
						"/conversations",
						{
							method: "POST",
							body: JSON.stringify({
								scope_type: "paper",
								scope_id: documentId,
							}),
						},
					)) as Conversation;
					if (!cancelled) {
						setConversationId(created.id);
						setConversation(created);
					}
				} catch {
					if (!cancelled) setIsFetchingHistory(false);
				}
			} catch {
				if (!cancelled) setIsFetchingHistory(false);
			}
		}

		void loadConversation();
		return () => {
			cancelled = true;
		};
	}, [enabled, initialConversationId, documentId]);

	useEffect(() => {
		if (enabled) void fetchMoreMessages();
	}, [enabled, fetchMoreMessages]);

	const handleScroll = useCallback(() => {
		if (messagesContainerRef.current?.scrollTop === 0) {
			void fetchMoreMessages();
		}
	}, [fetchMoreMessages]);

	const scrollToLatestMessage = useCallback(() => {
		const container = messagesContainerRef.current;
		if (!container || messages.length === 0) return;
		const elements = container.querySelectorAll("[data-message-index]");
		elements[elements.length - 1]?.scrollIntoView({
			behavior: "smooth",
			block: "start",
		});
	}, [messages.length]);

	return {
		conversationId,
		conversation,
		fetchMoreMessages,
		handleScroll,
		hasMoreMessages,
		isFetchingHistory,
		isLoadingMoreMessages,
		messages,
		messagesContainerRef,
		scrollToLatestMessage,
		setMessages,
	};
}
