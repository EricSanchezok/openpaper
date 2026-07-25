"use client";

import dynamic from "next/dynamic";

import EnigmaticLoadingExperience from "@/components/EnigmaticLoadingExperience";
import type { PdfHighlighterViewerProps } from "./pdf-viewer/viewerTypes";

export type {
	PdfHighlighterViewerProps,
	RenderedHighlightPosition,
} from "./pdf-viewer/viewerTypes";

const BrowserPdfHighlighterViewer = dynamic(
	() =>
		import("./PdfHighlighterViewerClient").then(
			(module) => module.PdfHighlighterViewer
		),
	{
		ssr: false,
		loading: () => <EnigmaticLoadingExperience />,
	}
);

export function PdfHighlighterViewer(props: PdfHighlighterViewerProps) {
	return <BrowserPdfHighlighterViewer {...props} />;
}
