import { useEffect, type MutableRefObject } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";

interface PdfDocumentSyncProps {
	pdfDocument: PDFDocumentProxy;
	pdfDocumentRef: MutableRefObject<PDFDocumentProxy | null>;
	setPdfReady: (ready: boolean) => void;
	setNumPages: (pageCount: number) => void;
}

export function PdfDocumentSync({
	pdfDocument,
	pdfDocumentRef,
	setPdfReady,
	setNumPages,
}: PdfDocumentSyncProps) {
	useEffect(() => {
		pdfDocumentRef.current = pdfDocument;
		setPdfReady(true);
	}, [pdfDocument, pdfDocumentRef, setPdfReady]);

	useEffect(() => {
		setNumPages(pdfDocument.numPages);
	}, [pdfDocument.numPages, setNumPages]);

	return null;
}
