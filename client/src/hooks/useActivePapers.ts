import useSWR, { mutate as globalMutate } from "swr";
import { PaperItem } from "@/lib/schema";
import { fetchLibraryPapers } from "@/lib/documents";

export const ACTIVE_PAPERS_KEY = "/api/library/papers";

async function fetchActivePapers(): Promise<PaperItem[]> {
	const papers = await fetchLibraryPapers();
	return papers
		.filter((paper) => paper.status === "reading")
		.sort(
		(a, b) =>
			new Date(b.created_at || "").getTime() -
			new Date(a.created_at || "").getTime(),
		);
}

export function useActivePapers(enabled = true) {
	const { data, error, isLoading, mutate } = useSWR<PaperItem[]>(
		enabled ? ACTIVE_PAPERS_KEY : null,
		fetchActivePapers,
	);

	return {
		papers: data ?? [],
		error,
		isLoading,
		mutate,
	};
}

export function refreshActivePapers() {
	return globalMutate(ACTIVE_PAPERS_KEY);
}

export function removeActivePaper(documentId: string) {
	return globalMutate<PaperItem[]>(
		ACTIVE_PAPERS_KEY,
		(current) => current?.filter((paper) => paper.id !== documentId) ?? [],
		{ revalidate: false },
	);
}
