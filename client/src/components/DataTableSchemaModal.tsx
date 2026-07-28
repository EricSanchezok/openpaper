"use client";

import { Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

export interface FieldDefinition {
    id: string;
    label: string;
}

interface DataTableSchemaModalProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSubmit: (fields: FieldDefinition[]) => void;
    isCreating?: boolean;
}

export default function DataTableSchemaModal({
    open,
    onOpenChange,
    onSubmit,
    isCreating = false,
}: DataTableSchemaModalProps) {
    const [fields, setFields] = useState<FieldDefinition[]>([
        { id: crypto.randomUUID(), label: "" },
    ]);

    useEffect(() => {
        if (!open) {
            setFields([{ id: crypto.randomUUID(), label: "" }]);
        }
    }, [open]);

    const validFields = fields
        .map((field) => ({ ...field, label: field.label.trim() }))
        .filter((field) => field.label.length > 0);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Create data table</DialogTitle>
                    <DialogDescription>
                        Define the fields Scholens should extract from every paper.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-2">
                    {fields.map((field, index) => (
                        <div key={field.id} className="flex items-center gap-2">
                            <Input
                                value={field.label}
                                maxLength={200}
                                placeholder={`Field ${index + 1}`}
                                onChange={(event) =>
                                    setFields((current) =>
                                        current.map((candidate) =>
                                            candidate.id === field.id
                                                ? {
                                                    ...candidate,
                                                    label: event.target.value,
                                                }
                                                : candidate,
                                        ),
                                    )
                                }
                            />
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                disabled={fields.length === 1}
                                onClick={() =>
                                    setFields((current) =>
                                        current.filter(
                                            (candidate) => candidate.id !== field.id,
                                        ),
                                    )
                                }
                                aria-label="Remove field"
                            >
                                <Trash2 className="h-4 w-4" />
                            </Button>
                        </div>
                    ))}
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={fields.length >= 50}
                        onClick={() =>
                            setFields((current) => [
                                ...current,
                                { id: crypto.randomUUID(), label: "" },
                            ])
                        }
                    >
                        <Plus className="mr-2 h-4 w-4" />
                        Add field
                    </Button>
                </div>

                <DialogFooter>
                    <Button
                        type="button"
                        disabled={validFields.length === 0 || isCreating}
                        onClick={() => onSubmit(validFields)}
                    >
                        {isCreating && (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        Create
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
