import useSWR from 'swr';
import { PaperItem } from '@/lib/schema';
import { fetchLibraryPapers } from '@/lib/documents';

const LIBRARY_PAPERS_KEY = "/library/papers";

export function usePapers() {
	const { data, error, isLoading, mutate } = useSWR<PaperItem[]>(
		LIBRARY_PAPERS_KEY,
		fetchLibraryPapers,
	);

	const setPapers = (documentId: string, updatedPaper: PaperItem) => {
		if (data) {
			const updatedPapers = data.map(p => (p.document_id === documentId ? updatedPaper : p));
			mutate(updatedPapers, false); // Update local data without revalidating
		}
	};

	return {
		papers: data,
		error,
		isLoading,
		setPapers,
		mutate,
	};
}
