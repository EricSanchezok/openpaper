import {
    PaperHighlightAnnotation,
    ResearchItem,
    ResearchComment,
} from '@/lib/schema';
import { fetchFromApi } from '@/lib/api';
import { useEffect, useState } from 'react';

export function useAnnotations(paperId: string, projectId?: string | null) {
    const [annotations, setAnnotations] = useState<PaperHighlightAnnotation[]>([]);
    const toAnnotation = (
        comment: ResearchComment,
    ): PaperHighlightAnnotation => ({
        id: comment.id,
        highlight_id: comment.thread_id,
        paper_id: paperId,
        content: comment.content,
        role: comment.role,
        created_at: comment.created_at,
        created_by: comment.created_by,
    });

    const addAnnotation = async (highlightId: string, content: string) => {
        try {
            const savedComment = await fetchFromApi(
                `/api/highlight-threads/${highlightId}/comments`,
                {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ content }),
                },
            ) as ResearchComment;
            const savedAnnotation = toAnnotation(savedComment);
            setAnnotations(prev => [...prev, savedAnnotation]);
            return savedAnnotation;
        } catch (error) {
            console.error('Error saving annotation:', error);
            throw error;
        }
    };

    const removeAnnotation = async (annotationId: string) => {
        try {
            await fetchFromApi(`/api/annotation-comments/${annotationId}`, {
                method: 'DELETE',
            });

            const updatedAnnotations = annotations.filter(a => a.id !== annotationId);
            setAnnotations(updatedAnnotations);
        } catch (error) {
            console.error('Error removing annotation:', error);
            throw error;
        }
    };

    const updateAnnotation = async (annotationId: string, content: string) => {
        try {
            const updatedComment = await fetchFromApi(`/api/annotation-comments/${annotationId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content,
                }),
            }) as ResearchComment;
            const updatedAnnotation = toAnnotation(updatedComment);

            const updatedAnnotations = annotations.map(a =>
                a.id === annotationId ? updatedAnnotation : a
            );

            setAnnotations(updatedAnnotations);
            return updatedAnnotation;
        } catch (error) {
            console.error('Error updating annotation:', error);
            throw error;
        }
    };

    const fetchAnnotations = async () => {
        try {
            const response = await fetchFromApi(`/api/documents/${paperId}/highlight-threads`, {
                method: 'GET',
            }) as { items: ResearchItem[] };
            const loadedAnnotations = response.items.flatMap((item) =>
                item.highlight_thread?.comments.map(toAnnotation) ?? [],
            );

            setAnnotations(loadedAnnotations);
            return loadedAnnotations;
        } catch (error) {
            console.error('Error loading annotations:', error);
            throw error;
        }
    };

    const refreshAnnotations = async () => {
        await fetchAnnotations();
    };

    const renderAnnotations = (highlights: PaperHighlightAnnotation[]) => {
        for (const h of highlights) {
            const highlightAnnotations = annotations.filter(a => a.highlight_id === h.id);
            if (highlightAnnotations.length > 0) {
                // Find the highlight in the DOM, identified by the `data-highlight-id` attribute
                const highlightElement = document.querySelector(`[data-highlight-id="${h.id}"]`);
                if (highlightElement) {

                    const existingAnnotations = highlightElement.getElementsByClassName('annotation-tooltip');
                    if (existingAnnotations.length > 0) {
                        return; // Annotations already rendered
                    }
                    // Create a new div element for the annotation
                    const annotationElement = document.createElement('div');
                    annotationElement.classList.add('annotation-tooltip', 'absolute', 'bg-white', 'border', 'rounded', 'p-2', 'shadow-md', 'top-2', '-right-2', 'z-10', 'bg-yellow-300', 'rounded-full', 'w-4', 'h-4', 'z-10');

                    // Append the annotation element to the highlight element
                    highlightElement.appendChild(annotationElement);
                }
            }
        }
    };

    const getAnnotationsForHighlight = (highlightId: string) => {
        return annotations.filter(a => a.highlight_id === highlightId);
    };

    useEffect(() => {
        fetchAnnotations();
    }, [paperId, projectId]);

    return {
        annotations,
        setAnnotations,
        addAnnotation,
        removeAnnotation,
        updateAnnotation,
        fetchAnnotations,
        refreshAnnotations,
        getAnnotationsForHighlight,
        renderAnnotations,
    };
}
