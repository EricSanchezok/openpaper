import type { Formats } from "next-intl";

export const formats = {
  dateTime: {
    short: {
      year: "numeric",
      month: "short",
      day: "numeric",
    },
    timestamp: {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    },
  },
  number: {
    compact: {
      notation: "compact",
      maximumFractionDigits: 1,
    },
    percent: {
      style: "percent",
      maximumFractionDigits: 1,
    },
  },
} satisfies Formats;
