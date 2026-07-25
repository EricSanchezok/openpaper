import { useCallback, useEffect, useRef, useState } from "react";

import { fetchFromApi } from "@/lib/api";
import type { ChatMessage } from "@/lib/schema";

interface ConversationResponse {
	id: string;
}

interface MessagePageResponse {
	messages: ChatMessage[];
}

interface UseConversationHistoryOptions {
	paperId: string;
	enabled: boolean;
}

export function useConversationHistory({
	paperId,
	enabled,
}: UseConversationHistoryOptions) {
	const [conversationId, setConversationId] = useState<string | null>(null);
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const [hasMoreMessages, setHasMoreMessages] = useState(true);
	const [isLoadingMoreMessages, setIsLoadingMoreMessages] = useState(false);
	const [isFetchingHistory, setIsFetchingHistory] = useState(true);
	const [page, setPage] = useState(1);
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
			const response = (await fetchFromApi(
				`/api/conversation/${conversationId}?page=${page}`,
				{ method: "GET" },
			)) as MessagePageResponse;
			const fetchedMessages = response.messages.map((message) => ({
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
			setPage((current) => current + 1);
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
		page,
	]);

	useEffect(() => {
		if (!enabled || !paperId) return;

		let cancelled = false;
		async function loadConversation() {
			try {
				let id: string | null = null;
				const existing = (await fetchFromApi(
					`/api/paper/conversation?paper_id=${paperId}`,
					{ method: "GET" },
				)) as ConversationResponse;
				id = existing.id || null;
				if (!cancelled) setConversationId(id);
			} catch {
				try {
					const created = (await fetchFromApi(
						`/api/conversation/paper/${paperId}`,
						{ method: "POST" },
					)) as ConversationResponse;
					if (!cancelled) setConversationId(created.id);
				} catch {
					if (!cancelled) setIsFetchingHistory(false);
				}
			}
		}

		void loadConversation();
		return () => {
			cancelled = true;
		};
	}, [enabled, paperId]);

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
