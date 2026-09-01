/** Backend timestamps (core/models_db.py's `_now()`) are naive UTC - no
 * timezone designator in the serialized ISO string. `new Date(iso)`
 * treats a designator-less datetime string as *local* time, not UTC, so
 * without this every timestamp silently shifts by the browser's UTC
 * offset (e.g. "updated 0m ago" everywhere on a non-UTC machine, since
 * the diff goes negative and gets clamped). Append Z so it's parsed as
 * the UTC instant it actually is. */
export function parseServerDate(iso) {
  const hasDesignator = /Z$|[+-]\d\d:\d\d$/.test(iso)
  return new Date(hasDesignator ? iso : `${iso}Z`)
}
