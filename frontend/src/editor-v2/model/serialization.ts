/**
 * Editor V2 — Serialization and schema migration.
 *
 * Projects are persisted as JSON. This module handles:
 * - Serializing a project to a plain object (stripping runtime-only state).
 * - Deserializing and validating a project from JSON.
 * - Migrating from older schema versions to the current version (2).
 */

import type { EditorProjectV2 } from "./types";
import { DEFAULT_CANVAS, DEFAULT_EXPORT } from "./types";

/** Current schema version. Bump when breaking changes are made. */
export const CURRENT_SCHEMA_VERSION = 2;

// ---------------------------------------------------------------------------
// Serialization
// ---------------------------------------------------------------------------

/**
 * Serialize a project to a JSON string.
 * Only includes persistable state (no DOM refs, AudioBuffers, etc.).
 */
export function serializeProject(project: EditorProjectV2): string {
  // The project type is already fully serializable by design.
  return JSON.stringify(project, null, 2);
}

/**
 * Deserialize a project from a JSON string, applying migrations if needed.
 * Throws if the JSON is not a valid project.
 */
export function deserializeProject(json: string): EditorProjectV2 {
  const raw = JSON.parse(json);
  return migrateProject(raw);
}

// ---------------------------------------------------------------------------
// Schema migration
// ---------------------------------------------------------------------------

/**
 * Migrate an unknown parsed object to the current EditorProjectV2 schema.
 * Supports:
 *   - Schema version 1 → 2 (hypothetical V1 format → V2 with canvas, export,
 *     selection, tracks)
 *   - Schema version 2: validated and returned as-is with defaults filled.
 */
export function migrateProject(raw: Record<string, unknown>): EditorProjectV2 {
  const version = (raw.schemaVersion as number) ?? 0;

  if (version < 1) {
    throw new Error(
      `Unknown or missing schemaVersion: ${version}. Cannot migrate.`,
    );
  }

  // V1 → V2 migration: hypothetical format upgrade
  if (version === 1) {
    return migrateV1toV2(raw);
  }

  if (version === 2) {
    return validateV2(raw as Partial<EditorProjectV2>);
  }

  // Future versions: fail loudly rather than silently dropping fields
  if (version > CURRENT_SCHEMA_VERSION) {
    throw new Error(
      `Project schema version ${version} is newer than supported (${CURRENT_SCHEMA_VERSION}). Please update InstaClip.`,
    );
  }

  throw new Error(`Unsupported schema version: ${version}`);
}

// ---------------------------------------------------------------------------
// V1 → V2 migration
// ---------------------------------------------------------------------------

/**
 * Migrate a schema-version-1 project to V2.
 *
 * V1 was a hypothetical predecessor with a flat segment list. This migration
 * creates proper tracks and normalizes items.
 */
function migrateV1toV2(raw: Record<string, unknown>): EditorProjectV2 {
  // Build a minimal valid V2 project, carrying over what we can.
  const project: EditorProjectV2 = {
    schemaVersion: 2,
    id: (raw.id as string) ?? `migrated_${Date.now()}`,
    name: (raw.name as string) ?? "Migrated Project",
    sourceCandidateId: raw.sourceCandidateId as string | undefined,
    revision: ((raw.revision as number) ?? 0) + 1,
    createdAt: (raw.createdAt as number) ?? Date.now(),
    updatedAt: Date.now(),
    canvas: (raw.canvas as EditorProjectV2["canvas"]) ?? { ...DEFAULT_CANVAS },
    assets: (raw.assets as EditorProjectV2["assets"]) ?? {},
    tracks: (raw.tracks as EditorProjectV2["tracks"]) ?? [],
    selection: { itemIds: [], focusedTrackId: null },
    view: { pixelsPerSecond: 64, scrollLeft: 0 },
    playhead: (raw.playhead as number) ?? 0,
    inPoint: null,
    outPoint: null,
    export: { ...DEFAULT_EXPORT },
    transitions: [],
  };

  // Ensure every track item has trackId set
  for (const track of project.tracks) {
    for (const item of track.items) {
      if (!item.trackId) item.trackId = track.id;
      if (item.speed == null) item.speed = 1;
      if (item.enabled == null) item.enabled = true;
      if (item.linkedGroupId === undefined) item.linkedGroupId = null;
    }
  }

  return project;
}

// ---------------------------------------------------------------------------
// V2 validation (fill defaults for optional fields)
// ---------------------------------------------------------------------------

function validateV2(raw: Partial<EditorProjectV2>): EditorProjectV2 {
  if (!raw.id) throw new Error("Project must have an id");

  const project: EditorProjectV2 = {
    schemaVersion: 2,
    id: raw.id,
    name: raw.name ?? "Untitled",
    sourceCandidateId: raw.sourceCandidateId,
    contentMode: raw.contentMode,
    longformPlan: structuredClone(raw.longformPlan),
    revision: raw.revision ?? 0,
    createdAt: raw.createdAt ?? Date.now(),
    updatedAt: raw.updatedAt ?? Date.now(),
    canvas: raw.canvas ?? { ...DEFAULT_CANVAS },
    assets: structuredClone(raw.assets ?? {}),
    tracks: structuredClone(raw.tracks ?? []),
    selection: structuredClone(raw.selection ?? { itemIds: [], focusedTrackId: null }),
    view: structuredClone(raw.view ?? { pixelsPerSecond: 64, scrollLeft: 0 }),
    playhead: raw.playhead ?? 0,
    inPoint: raw.inPoint ?? null,
    outPoint: raw.outPoint ?? null,
    export: raw.export ?? { ...DEFAULT_EXPORT },
    transitions: structuredClone(raw.transitions ?? []),
  };

  // Validate and fill item defaults
  for (const track of project.tracks) {
    for (const item of track.items) {
      if (item.speed == null) item.speed = 1;
      if (item.enabled == null) item.enabled = true;
      if (item.linkedGroupId === undefined) item.linkedGroupId = null;
    }
  }

  return project;
}
