/**
 * Editor V2 — Undo / Redo history manager.
 *
 * Stores immutable project snapshots. The reducer produces new project states;
 * this module tracks them for rewinding.
 *
 * Not persisted — runtime only. On reload the project is restored from its
 * last saved state; undo history is lost.
 */

import type { EditorProjectV2, Command, ClipboardEntry } from "./types";
import { reduce, cloneProject } from "./reducer";

export type HistoryEntry = {
  /** The project state before the command was applied. */
  project: EditorProjectV2;
  /** The command that produced the *next* state from this snapshot. */
  command: Command;
};

export type EditorHistory = {
  /** The current project state. */
  current: EditorProjectV2;
  /** Past states (newest at end). */
  undoStack: HistoryEntry[];
  /** Future states (newest at end) — cleared on any new command. */
  redoStack: HistoryEntry[];
  /** Maximum number of undo entries to retain. */
  maxDepth: number;
  /** Runtime clipboard — not serialized. */
  clipboard: ClipboardEntry | null;
};

const DEFAULT_MAX_DEPTH = 100;

/** Create a fresh history from an initial project. */
export function createHistory(
  project: EditorProjectV2,
  maxDepth: number = DEFAULT_MAX_DEPTH,
): EditorHistory {
  return {
    current: cloneProject(project),
    undoStack: [],
    redoStack: [],
    maxDepth,
    clipboard: null,
  };
}

/** Apply a command, pushing the previous state onto the undo stack. */
export function applyCommand(
  history: EditorHistory,
  command: Command,
): EditorHistory {
  const { project: next, clipboard } = reduce(
    history.current,
    command,
    history.clipboard,
  );

  const entry: HistoryEntry = {
    project: cloneProject(history.current),
    command,
  };

  const undoStack = [...history.undoStack, entry];
  // Trim to max depth
  while (undoStack.length > history.maxDepth) {
    undoStack.shift();
  }

  return {
    current: next,
    undoStack,
    redoStack: [], // New command clears redo
    maxDepth: history.maxDepth,
    clipboard,
  };
}

/** Undo the last command. Returns the same history if nothing to undo. */
export function undo(history: EditorHistory): EditorHistory {
  if (history.undoStack.length === 0) return history;

  const undoStack = [...history.undoStack];
  const entry = undoStack.pop()!;

  const redoEntry: HistoryEntry = {
    project: cloneProject(history.current),
    command: entry.command,
  };

  return {
    current: entry.project,
    undoStack,
    redoStack: [...history.redoStack, redoEntry],
    maxDepth: history.maxDepth,
    clipboard: history.clipboard,
  };
}

/** Redo the last undone command. Returns the same history if nothing to redo. */
export function redo(history: EditorHistory): EditorHistory {
  if (history.redoStack.length === 0) return history;

  const redoStack = [...history.redoStack];
  const entry = redoStack.pop()!;

  const undoEntry: HistoryEntry = {
    project: cloneProject(history.current),
    command: entry.command,
  };

  return {
    current: entry.project,
    undoStack: [...history.undoStack, undoEntry],
    redoStack,
    maxDepth: history.maxDepth,
    clipboard: history.clipboard,
  };
}

/** Check if undo is available. */
export function canUndo(history: EditorHistory): boolean {
  return history.undoStack.length > 0;
}

/** Check if redo is available. */
export function canRedo(history: EditorHistory): boolean {
  return history.redoStack.length > 0;
}
