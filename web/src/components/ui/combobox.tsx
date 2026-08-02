"use client";

import { Check, NavArrowDown, Search } from "iconoir-react";
import { useMemo, useState } from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { Button } from "./button";
import { Input } from "./input";
import { Popover, PopoverContent, PopoverTrigger } from "./tooltip-popover";

export type ComboboxOption = { label: string; value: string };

export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = "Select an option",
  searchPlaceholder = "Search",
}: {
  options: ComboboxOption[];
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
}) {
  const [query, setQuery] = useState("");
  const selected = options.find((option) => option.value === value);
  const filtered = useMemo(
    () =>
      options.filter((option) =>
        option.label.toLowerCase().includes(query.toLowerCase()),
      ),
    [options, query],
  );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          aria-label={placeholder}
          className="w-full justify-between font-normal"
          variant="secondary"
        >
          {selected?.label ?? placeholder}
          <Icon glyph={NavArrowDown} size={16} tone="secondary" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-1">
        <div className="relative p-1">
          <Icon
            className="absolute top-1/2 left-3 -translate-y-1/2"
            glyph={Search}
            size={16}
            tone="secondary"
          />
          <Input
            aria-label={searchPlaceholder}
            className="h-9 pl-9"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={searchPlaceholder}
            value={query}
          />
        </div>
        <div className="mt-1 max-h-56 overflow-auto">
          {filtered.length ? (
            filtered.map((option) => (
              <button
                className={cn(
                  "hover:bg-hover flex min-h-9 w-full items-center rounded-[var(--radius-md)] px-2 text-left text-sm",
                  option.value === value && "bg-subtle",
                )}
                key={option.value}
                onClick={() => onValueChange?.(option.value)}
                type="button"
              >
                <span className="flex-1">{option.label}</span>
                {option.value === value && <Icon glyph={Check} size={16} />}
              </button>
            ))
          ) : (
            <p className="text-muted px-3 py-6 text-center text-sm">
              No results
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
