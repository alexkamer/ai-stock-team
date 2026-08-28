// Module-scoped, so it survives unmounting the Brokerage page (e.g.
// navigating away and back) for as long as the SPA stays loaded. Lets the
// page paint the last-known data immediately while a fresh fetch runs
// underneath to replace it - a lightweight stale-while-revalidate cache.
export const brokerageCache = {
  connections: null,
  portfolio: null,
  updatedAt: null,
  positionsByAccount: {},
  balancesByAccount: {},
  ordersByAccount: {},
  newsByAccount: {},
}
