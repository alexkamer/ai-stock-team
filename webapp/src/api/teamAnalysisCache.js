// Module-scoped, so it survives unmounting StockTeam (e.g. tabbing away to
// Overview/Charts/News and back) for as long as the SPA stays loaded. A team
// analysis run is a real multi-agent Bedrock call chain (5 specialists + a
// synthesizer), not a cheap quote lookup, so re-running it on every tab
// switch would be both slow and wasteful - this caches the finished result
// per ticker until the user explicitly asks for a new one.
export const teamAnalysisCache = {}
