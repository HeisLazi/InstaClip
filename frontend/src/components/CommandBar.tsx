/**
 * Command Bar — Raycast/Arc-style global action picker.
 *
 * Open with Ctrl+K (or Cmd+K). Fuzzy-filter through:
 *   - sidebar destinations (Dashboard, Gallery, …)
 *   - one-click pipeline actions (run batch, sync Twitch, retrain, …)
 *
 * Doc reference: Section "Keyboard-First Navigation (Command Bars)".
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  BookOpenCheck,
  Image,
  ListChecks,
  Search,
  Settings as SettingsIcon,
  Scissors,
  Sparkles,
  Wand2,
  LayoutDashboard,
  Languages,
  MessagesSquare,
  PlayCircle,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import { api } from "@/api/client";
import { IS_CLIPPER, type PageKey } from "@/nav";
import { cn } from "@/lib/utils";

interface CommandBarProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (page: PageKey) => void;
}

interface ActionItem {
  id: string;
  label: string;
  icon: LucideIcon;
  group: string;
  hint?: string;
  keywords?: string;
  perform: () => Promise<void> | void;
}

export function CommandBar({ open, onClose, onNavigate }: CommandBarProps) {
  const [value, setValue] = useState("");
  const qc = useQueryClient();

  useEffect(() => { if (open) setValue(""); }, [open]);

  const actions: ActionItem[] = useMemo(() => {
    const go = (p: PageKey, label: string, icon: LucideIcon, hint?: string): ActionItem => ({
      id: `go:${p}`,
      label,
      icon,
      group: "Navigate",
      hint,
      perform: () => { onNavigate(p); onClose(); },
    });

    const clipperNavigation = [
      go("dashboard",    "Go to Dashboard",     LayoutDashboard),
      go("gallery",      "Go to Gallery",       Image),
      go("clip-room",    "Go to Clip Room",     MessagesSquare),
      go("editor",       "Go to Editor",        Scissors),
      go("tutorial",     "Replay guided setup", BookOpenCheck),
      go("onboarding",   "Go to Taste Setup",   ListChecks),
      go("profile",      "Go to Profile Tuner", Wand2),
      go("language",     "Go to Language Studio", Languages),
      go("account",      "Go to Account & Usage", UserRound),
      go("preferences",  "Go to Local Settings", SettingsIcon),
    ];
    // Owner-only pages removed in the public edition. Keep only the
    // clipper-visible navigation so the `PageKey` type stays closed.
    const fullNavigation = clipperNavigation;

    const clipperActions: ActionItem[] = [
      {
        id: "act:batch",
        label: "Open batch picker",
        icon: PlayCircle,
        group: "Run",
        hint: "Open Dashboard and choose local VODs",
        keywords: "batch pipeline many",
        perform: () => { onNavigate("dashboard"); onClose(); },
      },
    ];
    const fullActions: ActionItem[] = [
      // Owner-only actions that navigate to deleted pages are removed.
      // Keep only generic run actions that stay inside the clipper pageset.
      {
        id: "act:suggest_profile",
        label: "Ask LLM to tune profile",
        icon: Sparkles,
        group: "Run",
        hint: "Compare good vs bad transcripts and propose edits",
        keywords: "llm suggest tune patch",
        perform: async () => {
          onNavigate("profile");
          // Fire the suggest job; ProfilePage's modal will pick it up via job_id.
          await api.profile.suggest();
          qc.invalidateQueries({ queryKey: ["jobs"] });
          onClose();
        },
      },
      {
        id: "act:batch",
        label: "Run a batch…",
        icon: PlayCircle,
        group: "Run",
        hint: "Opens Dashboard batch picker",
        keywords: "batch pipeline many",
        perform: () => { onNavigate("dashboard"); onClose(); },
      },
    ];
    return IS_CLIPPER
      ? [...clipperNavigation, ...clipperActions]
      : [...fullNavigation, ...fullActions];
  }, [onNavigate, onClose, qc]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[14vh] bg-background/70 backdrop-blur-md"
      onClick={onClose}
    >
      <Command
        label="Command Bar"
        className="glass-strong modal-shell w-[min(640px,94vw)] rounded-xl overflow-hidden border border-border/40"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-3 border-b border-border/40">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Command.Input
            value={value}
            onValueChange={setValue}
            placeholder="Type a command or search…"
            className="flex-1 bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            autoFocus
          />
          <kbd className="kbd">Esc</kbd>
        </div>

        <Command.List className="max-h-[420px] overflow-y-auto py-1">
          <Command.Empty className="text-center text-xs text-muted-foreground py-6">
            No matches.
          </Command.Empty>

          {(["Navigate", "Run", "Open"] as const).map((group) => {
            const items = actions.filter((a) => a.group === group);
            if (!items.length) return null;
            return (
              <Command.Group
                key={group}
                heading={
                  <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground px-3 py-1">
                    {group}
                  </div>
                }
              >
                {items.map((a) => {
                  const Icon = a.icon;
                  return (
                    <Command.Item
                      key={a.id}
                      value={`${a.label} ${a.keywords ?? ""}`}
                      onSelect={() => { void a.perform(); }}
                      className={cn(
                        "flex items-center gap-3 px-3 py-2 cursor-pointer",
                        "aria-selected:bg-accent/40 rounded mx-1",
                      )}
                    >
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm">{a.label}</div>
                        {a.hint && (
                          <div className="text-[11px] text-muted-foreground truncate">{a.hint}</div>
                        )}
                      </div>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            );
          })}
        </Command.List>

        <div className="border-t border-border/40 px-3 py-2 text-[10px] text-muted-foreground flex items-center justify-between">
          <span>
            <kbd className="kbd">↑↓</kbd> navigate · <kbd className="kbd">Enter</kbd> run · <kbd className="kbd">Esc</kbd> close
          </span>
          <span>Ctrl + K anywhere</span>
        </div>
      </Command>
    </div>
  );
}
