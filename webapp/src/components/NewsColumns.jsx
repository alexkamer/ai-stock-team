import TickerBadge from './TickerBadge'
import './NewsColumns.css'

function timeAgo(isoDate) {
  const published = new Date(isoDate)
  if (Number.isNaN(published.getTime())) return ''
  const minutes = Math.max(1, Math.round((Date.now() - published.getTime()) / 60000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function NewsColumn({ label, articles }) {
  return (
    <div className="news-column">
      <span className="news-column__label">{label}</span>
      {articles === null
        ? Array.from({ length: 5 }, (_, i) => <div key={i} className="news-column__row news-column__row--loading" />)
        : articles.length === 0
        ? <div className="news-column__empty">No headlines right now.</div>
        : articles.map((article) => (
            <a key={article.url} href={article.url} target="_blank" rel="noreferrer" className="news-column__row">
              <p className="news-column__title">{article.title}</p>
              <span className="news-column__meta">
                <TickerBadge ticker={article.ticker} percent={article.ticker_day_change_percent} />
                {article.publisher}
                {article.publisher && article.published_at ? ' · ' : ''}
                {timeAgo(article.published_at)}
              </span>
            </a>
          ))}
    </div>
  )
}

/** Three side-by-side text columns beneath the carousel, one per news
 * category (see NEWS_CATEGORY_TICKERS on the backend) - a lighter-weight
 * treatment than NewsFeed's thumbnail rows since three of these need to
 * fit across the width of one NewsFeed. */
export default function NewsColumns({ columns }) {
  return (
    <div className="news-columns">
      {columns.map((col) => (
        <NewsColumn key={col.key} label={col.label} articles={col.articles} />
      ))}
    </div>
  )
}
