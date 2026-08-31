// Module-scoped, so it survives unmounting the TrackRecord page (e.g.
// navigating away and back) for as long as the SPA stays loaded. Lets the
// page paint the last-known data immediately while a fresh fetch runs
// underneath to replace it - a lightweight stale-while-revalidate cache.
export const trackRecordCache = {
  byKey: {},
}
