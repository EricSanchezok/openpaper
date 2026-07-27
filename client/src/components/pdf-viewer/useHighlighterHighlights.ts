import { useState, useEffect, useCallback } from "react";
import { PaperHighlight, ScaledPosition, HighlightColor } from "@/lib/schema";
import { fetchFromApi } from "@/lib/api";

export function useHighlighterHighlights(
	paperId: string,
	projectId?: string | null,
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
			const data: PaperHighlight[] = await fetchFromApi(
				`/api/highlight/${paperId}${projectId ? `?project_id=${projectId}` : ""}`,
				{
					method: "GET",
					headers: {
						"Content-Type": "application/json",
						Accept: "application/json",
					},
				}
			);

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
			console.error("Error loading highlights from server:", error);
		}
	}, [paperId, projectId]);

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
			paper_id: paperId,
			raw_text: highlight.raw_text,
			page_number: highlight.page_number,
			position: highlight.position,
			role: highlight.role || "user",
			color: highlight.color,
			project_id: projectId || undefined,
		};

		try {
			const data = await fetchFromApi(`/api/highlight`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
				body: JSON.stringify(payload),
			});
			return data;
		} catch (error) {
			console.error("Error sending highlight to server:", error);
		}
	};

	// Remove highlight from server
	const removeHighlightFromServer = async (highlight: PaperHighlight) => {
		try {
			await fetchFromApi(`/api/highlight/${highlight.id}`, {
				method: "DELETE",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
				},
			});

			setHighlights((prev) => prev.filter((h) => h.id !== highlight.id));
		} catch (error) {
			console.error("Error removing highlight from server:", error);
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
				console.error("Position is required for highlights");
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
				console.error("Error adding highlight:", error);
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
	}, [paperId, readOnlyHighlights.length, fetchHighlights]);

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
