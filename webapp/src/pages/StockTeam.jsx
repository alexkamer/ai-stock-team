import { useParams } from 'react-router-dom'

// Phase 3 (WEBAPP_ROADMAP.md) - not yet built. Placeholder so Dashboard's
// quick-nav card has somewhere to land instead of a dead route.
export default function StockTeam() {
  const { ticker } = useParams()
  return (
    <div className="card">
      <h2>Stock Team Analysis</h2>
      <p>Coming in Phase 3 - fundamentals + sentiment specialist cards and a synthesizer verdict for {ticker}.</p>
    </div>
  )
}
