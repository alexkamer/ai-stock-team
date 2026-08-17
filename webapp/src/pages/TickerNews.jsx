import { useOutletContext } from 'react-router-dom'
import NewsFeed from '../components/NewsFeed'

export default function TickerNews() {
  const { quote } = useOutletContext()

  if (quote !== null && !quote?.news_headlines) return null

  return (
    <div className="ticker-detail__news">
      <span className="eyebrow">Recent news</span>
      <NewsFeed articles={quote?.news ?? null} showTicker={false} summarizable />
    </div>
  )
}
