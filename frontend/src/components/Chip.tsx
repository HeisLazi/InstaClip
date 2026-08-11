/**
 * Removable chip used in the Profile editor (highlight_words etc.).
 * Click the ✕ to delete from the list.
 */

import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChipProps {
  label: string;
  onRemove?: () => void;
  tone?: "default" | "positive" | "negative";
  title?: string;
}

const TONE: Record<NonNullable<ChipProps["tone"]>, string> = {
  default:
    "bg-secondary/60 border-border/60 text-foreground/85 hover:bg-secondary",
  positive:
    "bg-success/15 border-success/40 text-success hover:bg-success/20",
  negative:
    "bg-destructive/15 border-destructive/40 text-destructive hover:bg-destructive/20",
};

export function Chip({ label, onRemove, tone = "default", title }: ChipProps) {
  return (
    <span
      title={title ?? label}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] leading-5 max-w-full transition-colors",
        TONE[tone],
      )}
    >
      <span className="truncate">{label}</span>
      {onRemove && (
        <button
          onClick={onRemove}
          className="rounded-full p-0.5 hover:bg-black/20 dark:hover:bg-white/10"
          title="Remove"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}
