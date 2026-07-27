"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { fetchFromApi } from "@/lib/api";
import { Button } from "@/components/ui/button";

type AcceptanceState = "accepting" | "accepted" | "failed";

export default function ProjectInvitationPage() {
    const params = useParams<{ token: string }>();
    const router = useRouter();
    const started = useRef(false);
    const [state, setState] = useState<AcceptanceState>("accepting");
    const [message, setMessage] = useState(
        "Checking the invitation and adding you to the project…",
    );

    useEffect(() => {
        if (started.current) return;
        started.current = true;

        const accept = async () => {
            try {
                await fetchFromApi(
                    `/api/project-invitations/token/${encodeURIComponent(params.token)}/accept`,
                    { method: "POST" },
                );
                setState("accepted");
                setMessage("You now have access to the project.");
            } catch (error) {
                setState("failed");
                setMessage(
                    error instanceof Error
                        ? error.message
                        : "This invitation is invalid or has expired.",
                );
            }
        };

        void accept();
    }, [params.token]);

    return (
        <main className="flex min-h-[60vh] items-center justify-center px-4">
            <div className="w-full max-w-md rounded-xl border p-8 text-center">
                {state === "accepting" && (
                    <Loader2 className="mx-auto mb-4 h-8 w-8 animate-spin text-muted-foreground" />
                )}
                {state === "accepted" && (
                    <CheckCircle2 className="mx-auto mb-4 h-8 w-8 text-green-600" />
                )}
                {state === "failed" && (
                    <XCircle className="mx-auto mb-4 h-8 w-8 text-destructive" />
                )}
                <h1 className="text-xl font-semibold">
                    {state === "accepting"
                        ? "Accepting invitation"
                        : state === "accepted"
                            ? "Invitation accepted"
                            : "Unable to accept invitation"}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground">{message}</p>
                {state !== "accepting" && (
                    <Button className="mt-6" onClick={() => router.replace("/projects")}>
                        Go to projects
                    </Button>
                )}
            </div>
        </main>
    );
}
