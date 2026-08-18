// Module-scoped, so a batch run survives switching away from the Team
// Review tab (or navigating elsewhere entirely) - the underlying fetch
// streams aren't tied to this module, only to whether something calls
// .abort() on them, so as long as TeamReviewTab doesn't do that on
// unmount, each analysis keeps running and logging server-side regardless
// of what the user does in the UI meanwhile.
export const teamReviewCache = {
  statusByTicker: {},
}
