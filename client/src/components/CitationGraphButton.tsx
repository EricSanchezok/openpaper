"use client";

import React, { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { SquareLibrary } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { fetchPaperData as fetchDocumentPaperData } from '@/lib/documents';
import Link from 'next/link';

export function CitationGraphButton() {
    const pathname = usePathname();
    const [documentId, setDocumentId] = useState<string | null>(null);
    const [paperDoi, setPaperDoi] = useState<string | null>(null);

    useEffect(() => {
        if (pathname) {
            const segments = pathname.split('/');
            if (segments[1] === 'paper' && segments.length === 3 && segments[2]) {
                setDocumentId(segments[2]);
            } else {
                setDocumentId(null);
            }
        }
    }, [pathname]);

    useEffect(() => {
        if (!documentId) return;

        const fetchPaperData = async () => {
            try {
                const data = await fetchDocumentPaperData(documentId);
                setPaperDoi(data.doi || null);
            } catch {
                setPaperDoi(null);
            }
        };

        fetchPaperData();
    }, [documentId]);

    // Only show button if paper has a DOI
    if (!documentId || !paperDoi) {
        return null;
    }

    return (
        <Button variant="ghost" size="sm" asChild>
            <Link href={`/graph?doi=${encodeURIComponent(paperDoi)}`}>
                <SquareLibrary className="h-4 w-4 mr-2" />
                Graph
            </Link>
        </Button>
    );
}
