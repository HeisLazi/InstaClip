/**
 * Progressive-disclosure log drawer.
 * Slides up from above the status bar when the user clicks "Logs".
 * Hosts the live stream from /stream/logs.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { subscribeLogs, type LogLine } from "@/api/client";
import { cn } from "@/lib/utils";
import { Trash2, X } from "lucide-react";

interface LogDrawerProps {
  open: boolean;
  onClose: () => void;
}

const LEVEL_COLOUR: Record<string, string> = {
  DEBUG:    "text-muted-foreground",
  INFO:     "text-foreground/80",
  WARNING:  "text-warning",
  ERROR:    "text-destructive",
  CRITICAL: "text-destructive",
};

export function LogDrawer({ open, onClose }: LogDrawerProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [filter, setFilter] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    if (!open) return;
    const close = subscribeLogs((line) => {
      setLines((prev) => {
        const next = prev.length > 5000 ? prev.slice(-3500) : prev.slice();
        next.push(line);
        return next;
      });
    });
    return close;
  }, [open]);

  useEffect(() => {
    if (!open || !stickToBottom.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, open]);

  const filtered = useMemo(() => {
    if (!filter.trim()) return lines;
    const f = filter.toLowerCase();
    return lines.filter(
      (l) => l.message.toLowerCase().includes(f) || l.logger.toLowerCase().includes(f),
    );
  }, [lines, filter]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  if (!open) return null;

  return (
    <div className="glass-strong border-t border-border/40 animate-drawer-up overflow-hidden flex flex-col"
         style={{ height: "min(40vh, 360px)" }}>
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border/50 text-xs">
        <span className="font-medium">Logs</span>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter…"
          className="flex-1 bg-secondary/50 px-2 py-1 rounded text-xs outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground"
        />
        <button
          onClick={() => setLines([])}
          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
          title="Clear visible log"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
          title="Close (Esc)"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto font-mono text-[11px] leading-snug px-3 py-2"
      >
        {filtered.length === 0 && (
          <div className="text-muted-foreground italic">No log lines yet.</div>
        )}
        {filtered.map((l, i) => (
          <div key={i} className="grid grid-cols-[60px_120px_1fr] gap-2">
            <span className={cn("uppercase", LEVEL_COLOUR[l.level] ?? "")}>{l.level}</span>
            <span className="text-muted-foreground truncate">{l.logger}</span>
            <span className="text-foreground/85 whitespace-pre-wrap break-words">{l.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
