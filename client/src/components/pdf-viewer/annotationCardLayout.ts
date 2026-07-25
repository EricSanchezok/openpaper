import type { PaperHighlight } from "@/lib/schema";

const CARD_WIDTH_PX = 280;
export const ANNOTATION_CARD_GAP_PX = 8;

export interface AnnotationCardEntry {
	highlightId: string;
	top: number;
	left: number;
	scrollContainer: Element;
	annotationId?: string;
	transientHighlight?: boolean;
}

interface PdfPageView {
	div: HTMLElement;
	viewport: { height: number };
}

export interface PdfViewerForAnnotations {
	getPageView(index: number): PdfPageView | undefined;
}

function resolveHighlightPageNumber(
	highlight: PaperHighlight,
	numPages: number | null,
): number | null {
	const positionPage = highlight.position?.boundingRect?.pageNumber;
	const stored = highlight.page_number;
	if (stored != null && numPages != null && stored >= 1 && stored <= numPages) {
		return stored;
	}
	if (
		positionPage != null &&
		numPages != null &&
		positionPage >= 1 &&
		positionPage <= numPages
	) {
		return positionPage;
	}
	if (stored != null && stored >= 1) return stored;
	if (positionPage != null && positionPage >= 1) return positionPage;
	return stored ?? positionPage ?? null;
}

function anchorFromOverlay(
	highlightId: string | undefined,
	scrollContainer: HTMLElement,
): { top: number; left: number } | null {
	if (!highlightId) return null;
	const overlay = scrollContainer.querySelector<HTMLElement>(
		`.text-match-highlight-overlay[data-highlight-id="${CSS.escape(highlightId)}"]`,
	);
	if (!overlay) return null;

	const containerRect = scrollContainer.getBoundingClientRect();
	const overlayRect = overlay.getBoundingClientRect();
	const scrollLeft = scrollContainer.scrollLeft;
	const top =
		overlayRect.top - containerRect.top + scrollContainer.scrollTop;
	const pageElement = overlay.closest<HTMLElement>(".page");

	if (pageElement) {
		const pageRect = pageElement.getBoundingClientRect();
		const right =
			pageRect.right -
			containerRect.left +
			scrollLeft +
			ANNOTATION_CARD_GAP_PX;
		const left =
			pageRect.left -
			containerRect.left +
			scrollLeft -
			ANNOTATION_CARD_GAP_PX -
			CARD_WIDTH_PX;
		return {
			top,
			left:
				right + CARD_WIDTH_PX > scrollContainer.scrollWidth && left >= 0
					? left
					: right,
		};
	}

	return {
		top,
		left:
			overlayRect.right -
			containerRect.left +
			scrollLeft +
			ANNOTATION_CARD_GAP_PX,
	};
}

export function getAnnotationCardAnchor(
	highlight: PaperHighlight,
	viewer: PdfViewerForAnnotations,
	scrollContainer: HTMLElement,
	numPages: number | null = null,
): { top: number; left: number } | null {
	if (!highlight.position) {
		return anchorFromOverlay(highlight.id, scrollContainer);
	}

	const pageNumber = resolveHighlightPageNumber(highlight, numPages);
	if (!pageNumber) return null;
	const pageView = viewer.getPageView(pageNumber - 1);
	if (!pageView?.div || !pageView.viewport) return null;

	const { boundingRect } = highlight.position;
	const scaleY = pageView.viewport.height / boundingRect.height;
	const usesPdfCoordinates = Boolean(
		(highlight.position as { usePdfCoordinates?: boolean }).usePdfCoordinates,
	);
	const yOffset = usesPdfCoordinates
		? (boundingRect.height - boundingRect.y2) * scaleY
		: boundingRect.y1 * scaleY;
	const containerRect = scrollContainer.getBoundingClientRect();
	const pageRect = pageView.div.getBoundingClientRect();
	const scrollLeft = scrollContainer.scrollLeft;
	const top =
		pageRect.top -
		containerRect.top +
		scrollContainer.scrollTop +
		yOffset;
	const right =
		pageRect.right -
		containerRect.left +
		scrollLeft +
		ANNOTATION_CARD_GAP_PX;
	const left =
		pageRect.left -
		containerRect.left +
		scrollLeft -
		ANNOTATION_CARD_GAP_PX -
		CARD_WIDTH_PX;

	return {
		top,
		left:
			right + CARD_WIDTH_PX > scrollContainer.scrollWidth && left >= 0
				? left
				: right,
	};
}
