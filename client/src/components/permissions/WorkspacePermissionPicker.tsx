"use client";

import { useId } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import {
	serializeWorkspacePermissions,
	WORKSPACE_PERMISSION_OPTIONS,
	type WorkspacePermission,
} from "@/lib/workspace-permissions";

interface WorkspacePermissionPickerProps {
	value: readonly WorkspacePermission[];
	onChange: (value: WorkspacePermission[]) => void;
	disabled?: boolean;
	className?: string;
}

export function WorkspacePermissionPicker({
	value,
	onChange,
	disabled = false,
	className,
}: WorkspacePermissionPickerProps) {
	const idPrefix = useId();
	const selected = new Set(value);

	return (
		<fieldset
			disabled={disabled}
			className={cn("flex flex-wrap items-center gap-x-3 gap-y-2", className)}
		>
			<legend className="sr-only">Agent tool permissions</legend>
			{WORKSPACE_PERMISSION_OPTIONS.map((option) => {
				const id = `${idPrefix}-${option.value}`;
				return (
					<label
						key={option.value}
						htmlFor={id}
						title={option.description}
						className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
					>
						<Checkbox
							id={id}
							checked={selected.has(option.value)}
							disabled={disabled}
							onCheckedChange={(checked) => {
								const next = new Set(selected);
								if (checked === true) {
									next.add(option.value);
								} else {
									next.delete(option.value);
								}
								onChange(serializeWorkspacePermissions(next));
							}}
						/>
						{option.label}
					</label>
				);
			})}
		</fieldset>
	);
}
