import { reportClientIssue } from "@/lib/client-observability";
import React, { useState, useEffect, useRef } from 'react';
import { PaperUploadJobStatusResponse, JobStatus, MinimalJob } from "@/lib/schema";
import { fetchUploadJobStatus } from "@/lib/documents";
import { AlertTriangle, CheckCircle2, ChevronDown, XCircle, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

interface Job extends MinimalJob {
	status: JobStatus;
	details?: PaperUploadJobStatusResponse;
	documentId?: string;
}

interface PdfUploadTrackerProps {
	initialJobs: MinimalJob[];
	onComplete: (documentId: string) => void;
}

// Track jobs that have already triggered onComplete - persists across component remounts
// This prevents the infinite loop: complete -> refetch -> unmount -> remount -> complete again
// Also stores documentId so we can restore full job state on remount
const completedJobs = new Map<string, string>(); // jobId -> documentId

const PdfUploadTracker: React.FC<PdfUploadTrackerProps> = ({ initialJobs, onComplete }) => {
	const [jobs, setJobs] = useState<Job[]>([]);
	const [isOpen, setIsOpen] = useState(false);
	const [pollingTrigger, setPollingTrigger] = useState(0);
	const jobsRef = useRef<Job[]>(jobs);
	const onCompleteRef = useRef(onComplete);

	// Keep refs in sync with current values
	useEffect(() => {
		jobsRef.current = jobs;
	}, [jobs]);

	useEffect(() => {
		onCompleteRef.current = onComplete;
	}, [onComplete]);

	useEffect(() => {
		let addedNewPending = false;
		setJobs(prevJobs => {
			const newJobs = initialJobs.filter(ij => !prevJobs.some(pj => pj.jobId === ij.jobId));
			if (newJobs.some(j => !completedJobs.has(j.jobId))) {
				addedNewPending = true;
			}
			return [...prevJobs, ...newJobs.map(j => {
				// If this job already completed, restore its completed status and documentId
				const completedDocumentId = completedJobs.get(j.jobId);
				return {
					...j,
					status: completedDocumentId ? 'completed' as JobStatus : 'pending' as JobStatus,
					documentId: completedDocumentId
				};
			})];
		});
		// Restart polling when new pending jobs arrive
		if (addedNewPending) {
			setPollingTrigger(prev => prev + 1);
		}
	}, [initialJobs]);

	useEffect(() => {
		const interval = setInterval(async () => {
			const currentJobs = jobsRef.current;
			if (currentJobs.length === 0) return;

			let hasPendingJobs = false;
			for (const job of currentJobs) {
				// Skip jobs that have already completed (including across remounts)
				if (completedJobs.has(job.jobId)) continue;

				if (job.status === 'pending' || job.status === 'running') {
					hasPendingJobs = true;
					try {
						const statusResponse: PaperUploadJobStatusResponse =
							await fetchUploadJobStatus(job.jobId);
						setJobs(prevJobs => prevJobs.map(j => j.jobId === job.jobId ? {
							...j,
							status: statusResponse.status,
							details: statusResponse,
							documentId: statusResponse.document_id || j.documentId
						} : j));

						if (statusResponse.status === "completed" && statusResponse.document_id) {
							// Mark as completed before calling onComplete to prevent duplicate calls
							completedJobs.set(job.jobId, statusResponse.document_id);
							onCompleteRef.current(statusResponse.document_id);
						}
					} catch (err) {
						reportClientIssue(`Failed to get upload status for ${job.fileName}.`, err);
						setJobs(prevJobs => prevJobs.map(j => j.jobId === job.jobId ? { ...j, status: 'failed' } : j));
					}
				}
			}
			if (!hasPendingJobs) {
				clearInterval(interval);
			}
		}, 2000);

		return () => clearInterval(interval);
	}, [pollingTrigger]);

	// Calculate counts for summary
	const completedCount = jobs.filter(j => j.status === 'completed').length;
	const failedCount = jobs.filter(j => j.status === 'failed').length;
	const degradedCount = jobs.filter(
		j => j.status === 'completed' && j.details?.parser_quality === 'text_only'
	).length;
	const inProgressCount = jobs.filter(j => j.status === 'pending' || j.status === 'running').length;
	const totalCount = jobs.length;

	// Don't render if no jobs
	if (jobs.length === 0) {
		return null;
	}

	const allDone = inProgressCount === 0;
	const hasFailures = failedCount > 0;
	const hasDegraded = degradedCount > 0;

	return (
		<Collapsible open={isOpen} onOpenChange={setIsOpen} className="w-full min-w-0 mb-4">
			<CollapsibleTrigger className="w-full">
				<div className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
					allDone
						? hasFailures || hasDegraded
							? 'bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800'
							: 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800'
						: 'bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800'
				}`}>
					<div className="flex items-center gap-3">
						{allDone ? (
							hasFailures ? (
								<XCircle className="w-5 h-5 text-amber-500" />
							) : hasDegraded ? (
								<AlertTriangle className="w-5 h-5 text-amber-500" />
							) : (
								<CheckCircle2 className="w-5 h-5 text-green-500" />
							)
						) : (
							<Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
						)}
						<span className="text-sm font-medium">
							{allDone
								? hasFailures
									? `Uploads complete with ${failedCount} error${failedCount > 1 ? 's' : ''}`
									: hasDegraded
										? `${degradedCount} paper${degradedCount > 1 ? 's were' : ' was'} indexed in text-only mode`
									: `${totalCount} paper${totalCount > 1 ? 's' : ''} uploaded`
								: `Uploading papers`
							}
						</span>
						<span className="text-sm text-muted-foreground">
							{completedCount} of {totalCount} complete
						</span>
					</div>
					<ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`} />
				</div>
			</CollapsibleTrigger>
			<CollapsibleContent>
				<div className="mt-2 border rounded-lg divide-y">
					{jobs.map(job => (
						<div key={job.jobId} className="flex items-center justify-between p-3 gap-4 min-w-0">
							<div className="flex-1 min-w-0 overflow-hidden">
								{job.status === 'completed' && job.documentId ? (
									<Link
										href={`/paper/${job.documentId}`}
										className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 hover:underline cursor-pointer block truncate"
										title={job.fileName}
									>
										{job.fileName}
									</Link>
								) : (
									<span className="text-sm font-medium block truncate" title={job.fileName}>
										{job.fileName}
									</span>
								)}
							</div>
							<div className="flex-shrink-0">
								{(() => {
									switch (job.status) {
										case 'pending':
										case 'running':
											return (
												<div className="flex items-center gap-2 text-blue-500">
													<Loader2 className="w-4 h-4 animate-spin" />
													<span className="text-xs capitalize">{job.status}</span>
												</div>
											);
										case 'completed':
											if (job.details?.parser_quality === 'text_only') {
												return (
													<div
														className="flex items-center gap-2 text-amber-600 dark:text-amber-400"
														title="Equations, tables, and layout may be incomplete."
													>
														<AlertTriangle className="w-4 h-4" />
														<span className="text-xs">Text only</span>
													</div>
												);
											}
											return (
												<div className="flex items-center gap-2 text-green-500">
													<CheckCircle2 className="w-4 h-4" />
													<span className="text-xs">Done</span>
												</div>
											);
										case 'failed':
											return (
												<div className="flex items-center gap-2 text-red-500">
													<XCircle className="w-4 h-4" />
													<span className="text-xs">Failed</span>
												</div>
											);
										default:
											return <span className="text-xs text-muted-foreground capitalize">{job.status}</span>;
									}
								})()}
							</div>
						</div>
					))}
				</div>
			</CollapsibleContent>
		</Collapsible>
	);
};

export default PdfUploadTracker;
