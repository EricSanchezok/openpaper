import type { BasicUser } from "@/lib/auth";
import type {
	HighlightColor,
	PaperHighlight,
	PaperHighlightAnnotation,
	ScaledPosition,
} from "@/lib/schema";
import type { PaperStatus } from "@/components/utils/PdfStatus";
import type { Dispatch, SetStateAction } from "react";

export interface RenderedHighlightPosition {
	left: number;
	top: number;
	width: number;
	height: number;
	page: number;
}

export interface PdfHighlighterViewerProps {
	pdfUrl: string;
	explicitSearchTerm?: string;
	highlights: PaperHighlight[];
	setHighlights: (highlights: PaperHighlight[]) => void;
	selectedText: string;
	setSelectedText: (text: string) => void;
	tooltipPosition: { x: number; y: number } | null;
	setTooltipPosition: (position: { x: number; y: number } | null) => void;
	isAnnotating: boolean;
	setIsAnnotating: (isAnnotating: boolean) => void;
	isHighlightInteraction: boolean;
	setIsHighlightInteraction: (isHighlightInteraction: boolean) => void;
	activeHighlight: PaperHighlight | null;
	setActiveHighlight: (highlight: PaperHighlight | null) => void;
	addHighlight: (
		selectedText: string,
		position?: ScaledPosition,
		pageNumber?: number,
		doAnnotate?: boolean,
		color?: HighlightColor
	) => void;
	removeHighlight: (highlight: PaperHighlight) => void;
	loadHighlights: () => Promise<void>;
	renderAnnotations: (annotations: PaperHighlightAnnotation[]) => void;
	annotations: PaperHighlightAnnotation[];
	handleStatusChange?: (status: PaperStatus) => void;
	paperStatus?: PaperStatus;
	setUserMessageReferences: Dispatch<SetStateAction<string[]>>;
	onOverlaysCreated?: (positions: Map<string, RenderedHighlightPosition>) => void;
	onRefreshUrl?: () => Promise<string | null>;
	addAnnotation?: (
		highlightId: string,
		content: string
	) => Promise<PaperHighlightAnnotation>;
	updateAnnotation?: (
		annotationId: string,
		content: string
	) => Promise<unknown> | void;
	removeAnnotation?: (annotationId: string) => void;
	currentUser?: BasicUser | null;
	showAnnotationCards?: boolean;
	onToggleAnnotationCards?: () => void;
	annotationsPanelActive?: boolean;
	onAnnotateViaSidePanel?: (payload: { highlightId: string }) => void;
	sidePanelOpen?: boolean;
	isReadMode?: boolean;
	onToggleReadMode?: () => void;
}
