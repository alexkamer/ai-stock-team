// Module-scoped, same rationale as teamAnalysisCache.js: specialist accuracy
// is global (not per-ticker, see /track-record/specialists), so one fetch
// per SPA session is enough - it only changes as new verdicts get scored,
// not on every tab switch.
export const specialistStatsCache = { promise: null }
