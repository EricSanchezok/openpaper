import { reportClientIssue } from "@/lib/client-observability";
import { useState, useEffect, useCallback } from "react";
import {
	PaperHighlight,
	ScaledPosition,
	HighlightColor,
	ResearchItem,
} from "@/lib/schema";
import { fetchFromApi } from "@/lib/api";

function toHighlight(item: ResearchItem): PaperHighlight | null {
	const thread = item.highlight_thread;
	if (!thread) return null;
	return {
		id: item.id,
		raw_text: thread.quote_text,
		role: thread.role === "assistant" ? "assistant" : "user",
		start_offset: thread.start_offset ?? undefined,
		end_offset: thread.end_offset ?? undefined,
		page_number: thread.page_number ?? undefined,
		position: thread.position as unknown as ScaledPosition | undefined,
		color: thread.color as HighlightColor,
		is_shared: item.is_shared,
		created_by: item.created_by,
	};
}

export function useHighlighterHighlights(
	documentId: string,
	_projectId?: string | null,
	readOnlyHighlights: Array<PaperHighlight> = []
) {
	const [highlights, setHighlights] = useState<Array<PaperHighlight>>([]);
	const [selectedText, setSelectedText] = useState<string>("");
	const [tooltipPosition, setTooltipPosition] = useState<{
		x: number;
		y: number;
	} | null>(null);
	const [isAnnotating, setIsAnnotating] = useState(false);
	const [isHighlightInteraction, setIsHighlightInteraction] = useState(false);
	const [activeHighlight, setActiveHighlight] =
		useState<PaperHighlight | null>(null);

	// Fetch highlights from server
	const fetchHighlights = useCallback(async () => {
		try {
			const response = await fetchFromApi(
				`/papers/${documentId}/highlight-threads`,
				{
					method: "GET",
					headers: {
						"Content-Type": "application/json",
						Accept: "application/json",
					},
				}
			) as { items: ResearchItem[] };
			const data = response.items
				.map(toHighlight)
				.filter((highlight): highlight is PaperHighlight => highlight !== null);

			// Filter valid highlights - require either position or offsets
			const validHighlights = data.filter(
				(h) =>
					h.raw_text &&
					(h.position ||
						(typeof h.start_offset === "number" &&
							typeof h.end_offset === "number"))
			);

			// Deduplicate
			const deduplicatedHighlights = validHighlights.filter(
				(highlight, index, self) =>
					index ===
					self.findIndex(
						(h) =>
							h.id === highlight.id ||
							(h.raw_text === highlight.raw_text &&
								h.page_number === highlight.page_number)
					)
			);

			setHighlights(deduplicatedHighlights);
		} catch (error) {
			reportClientIssue("Error loading highlights from server:", error);
		}
	}, [documentId]);

	// Send highlight to server
	const sendHighlightToServer = async (
		highlight: Omit<PaperHighlight, "id">
	): Promise<PaperHighlight | undefined> => {
		// Check for duplicates
		const isDuplicate = highlights.some(
			(h) =>
				h.raw_text === highlight.raw_text &&
				h.page_number === highlight.page_number
		);

		if (isDuplicate) {
			return;
		}

		const payload = {
			quote_text: highlight.raw_text,
			page_number: highlight.page_number,
			start_offset: highlight.start_offset,
			end_offset: highlight.end_offset,
			position: highlight.position,
			color: highlight.color ?? "yellow",
			shared: true,
		};

		try {
			const item = await fetchFromApi(
				`/papers/${documentId}/highlight-threads`,
				{
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify(payload),
				},
			) as ResearchItem;
			return toHighlight(item) ?? undefined;
		} catch (error) {
			reportClientIssue("Error sending highlight to server:", error);
		}
	};

	// Remove highlight from server
	const removeHighlightFromServer = async (highlight: PaperHighlight) => {
		try {
			await fetchFromApi(`/highlight-threads/${highlight.id}`, {
				method: "DELETE",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
			}).catch(async () => {
				if (
					!window.confirm(
						"This highlight has replies from other collaborators. Delete the thread and all replies?",
					)
				) {
					throw new Error("highlight_delete_cancelled");
				}
				await fetchFromApi(
					`/highlight-threads/${highlight.id}?confirm_delete_replies=true`,
					{ method: "DELETE" },
				);
			});

			setHighlights((prev) => prev.filter((h) => h.id !== highlight.id));
		} catch (error) {
			reportClientIssue("Error removing highlight from server:", error);
		}
	};

	// Add a new highlight with position data
	const addHighlight = useCallback(
		async (
			selectedText: string,
			position?: ScaledPosition,
			pageNumber?: number,
			doAnnotate?: boolean,
			color?: HighlightColor
		) => {
			if (!position) {
				reportClientIssue("Position is required for highlights");
				return;
			}

			const newHighlight: Omit<PaperHighlight, "id"> = {
				raw_text: selectedText,
				role: "user",
				page_number: pageNumber || position.boundingRect.pageNumber,
				position: position,
				color: color,
			};

			try {
				const savedHighlight = await sendHighlightToServer(newHighlight);

				if (savedHighlight) {
					if (doAnnotate) {
						setActiveHighlight(savedHighlight);
						setIsAnnotating(true);
					}

					setHighlights((prev) => [...prev, savedHighlight]);
				}
			} catch (error) {
				reportClientIssue("Error adding highlight:", error);
			}

			// Reset states
			setSelectedText("");
			setTooltipPosition(null);
			if (!doAnnotate) {
				setIsAnnotating(false);
			}
		},
		[highlights]
	);

	// Remove a highlight
	const removeHighlight = useCallback((highlight: PaperHighlight) => {
		removeHighlightFromServer(highlight);
	}, []);

	// Clear highlights from state
	const clearHighlights = useCallback(() => {
		setHighlights([]);
	}, []);

	// Refresh highlights
	const refreshHighlights = useCallback(async () => {
		await fetchHighlights();
	}, [fetchHighlights]);

	// Load highlights on mount or when readOnlyHighlights changes
	useEffect(() => {
		if (readOnlyHighlights.length > 0) {
			setHighlights(readOnlyHighlights);
		} else {
			fetchHighlights();
		}
	}, [documentId, readOnlyHighlights.length, fetchHighlights]);

	// Reset interaction state when selectedText is cleared
	useEffect(() => {
		if (!selectedText) {
			setIsHighlightInteraction(false);
		}
	}, [selectedText]);

	return {
		highlights,
		setHighlights,
		selectedText,
		setSelectedText,
		tooltipPosition,
		setTooltipPosition,
		isAnnotating,
		setIsAnnotating,
		isHighlightInteraction,
		setIsHighlightInteraction,
		activeHighlight,
		setActiveHighlight,
		clearHighlights,
		addHighlight,
		removeHighlight,
		fetchHighlights,
		refreshHighlights,
	};
}
