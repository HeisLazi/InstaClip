/**
 * Stable ID generation for Editor V2.
 *
 * Uses crypto.randomUUID() for globally unique, serializable IDs.
 * Prefixed with a type hint for human readability in JSON dumps.
 */

let _counter = 0;

/**
 * Generate a unique ID with an optional human-readable prefix.
 * Falls back to a counter-based ID when crypto.randomUUID is unavailable
 * (e.g. non-secure test contexts).
 */
export function uid(prefix = ""): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    const raw = crypto.randomUUID();
    return prefix ? `${prefix}_${raw}` : raw;
  }
  _counter++;
  const ts = Date.now().toString(36);
  const seq = _counter.toString(36).padStart(4, "0");
  const id = `${ts}-${seq}`;
  return prefix ? `${prefix}_${id}` : id;
}

/** Convenience generators for each entity type. */
export const newProjectId = () => uid("proj");
export const newAssetId = () => uid("ast");
export const newTrackId = () => uid("trk");
export const newItemId = () => uid("itm");
export const newLinkedGroupId = () => uid("lnk");
