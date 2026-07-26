import { useCallback } from "react";
import useSWR from "swr";

import { useAuth } from "@/lib/auth";
import { fetchFromApi } from "@/lib/api";
import { SubscriptionData, UseSubscriptionReturn } from "@/lib/schema";

const SUBSCRIPTION_USAGE_KEY = "/api/subscription/usage";

async function fetchSubscriptionUsage(): Promise<SubscriptionData> {
    return fetchFromApi(SUBSCRIPTION_USAGE_KEY);
}

export const useSubscription = (): UseSubscriptionReturn => {
    const { user, loading: authLoading } = useAuth();
    const enabled = !authLoading && user !== null;
    const {
        data,
        error,
        isLoading,
        mutate,
    } = useSWR<SubscriptionData>(
        enabled ? SUBSCRIPTION_USAGE_KEY : null,
        fetchSubscriptionUsage,
    );

    const refetch = useCallback(async (): Promise<void> => {
        if (!enabled) return;
        await mutate();
    }, [enabled, mutate]);

    return {
        subscription: enabled ? data ?? null : null,
        loading: authLoading || (enabled && isLoading),
        error: enabled && error
            ? error instanceof Error
                ? error.message
                : "Failed to fetch subscription data"
            : null,
        refetch,
    };
};

// Helper functions for common subscription checks
export const getStorageUsagePercentage = (subscription: SubscriptionData | null): number => {
    if (!subscription) return 0;
    const total = subscription.limits.knowledge_base_size;
    if (total === 0) return 0;
    return (subscription.usage.knowledge_base_size / total) * 100;
};

export const isStorageNearLimit = (subscription: SubscriptionData | null, threshold: number = 75): boolean => {
    return getStorageUsagePercentage(subscription) >= threshold;
};

export const isStorageAtLimit = (subscription: SubscriptionData | null): boolean => {
    return getStorageUsagePercentage(subscription) >= 100;
};

export const getPaperUploadPercentage = (subscription: SubscriptionData | null): number => {
    if (!subscription) return 0;
    const total = subscription.limits.paper_uploads;
    if (total === 0) return 0;
    return (subscription.usage.paper_uploads / total) * 100;
};

export const isPaperUploadNearLimit = (subscription: SubscriptionData | null, threshold: number = 75): boolean => {
    return getPaperUploadPercentage(subscription) >= threshold;
};

export const isPaperUploadAtLimit = (subscription: SubscriptionData | null): boolean => {
    return getPaperUploadPercentage(subscription) >= 100;
};

export const formatFileSize = (sizeInKb: number): string => {
    if (sizeInKb < 1024) {
        return `${sizeInKb.toFixed(1)} KB`;
    } else if (sizeInKb < 1024 * 1024) {
        return `${(sizeInKb / 1024).toFixed(1)} MB`;
    } else {
        return `${(sizeInKb / (1024 * 1024)).toFixed(1)} GB`;
    }
};

// Token Credit helper functions
export const getTokenCreditUsagePercentage = (subscription: SubscriptionData | null): number => {
    if (!subscription) return 0;
    const total = subscription.limits.token_credits_weekly;
    if (total === 0) return 0;
    return (subscription.usage.token_credits_used / total) * 100;
};

export const isTokenCreditNearLimit = (subscription: SubscriptionData | null, threshold: number = 75): boolean => {
    return getTokenCreditUsagePercentage(subscription) >= threshold;
};

export const isTokenCreditAtLimit = (subscription: SubscriptionData | null): boolean => {
    return getTokenCreditUsagePercentage(subscription) >= 100;
};

// Project usage helper functions
export const getProjectUsagePercentage = (subscription: SubscriptionData | null): number => {
    if (!subscription) return 0;
    const total = subscription.limits.projects;
    if (total === 0) return 0;
    return (subscription.usage.projects / total) * 100;
};

export const isProjectNearLimit = (subscription: SubscriptionData | null, threshold: number = 75): boolean => {
    return getProjectUsagePercentage(subscription) >= threshold;
};

export const isProjectAtLimit = (subscription: SubscriptionData | null): boolean => {
    return getProjectUsagePercentage(subscription) >= 100;
};

export const getProjectPaperHardLimit = (subscription: SubscriptionData | null): number | null => {
    return subscription?.limits.project_papers ?? null;
};

const getProjectPaperUsagePercentage = (subscription: SubscriptionData | null, paperCount: number): number => {
    if (!subscription) return 0;
    const total = subscription.limits.project_papers;
    if (total === 0) return 0;
    return (paperCount / total) * 100;
};

export const isProjectPaperNearLimit = (subscription: SubscriptionData | null, paperCount: number, threshold: number = 75): boolean => {
    return getProjectPaperUsagePercentage(subscription, paperCount) >= threshold;
};

export const isProjectPaperAtLimit = (subscription: SubscriptionData | null, paperCount: number): boolean => {
    return getProjectPaperUsagePercentage(subscription, paperCount) >= 100;
};
