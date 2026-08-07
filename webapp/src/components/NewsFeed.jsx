import './NewsFeed.css'

function timeAgo(isoDate) {
  const published = new Date(isoDate)
  if (Number.isNaN(published.getTime())) return ''
  const minutes = Math.max(1, Math.round((Date.now() - published.getTime()) / 60000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function NewsRow({ article }) {
  return (
    <a href={article.url} target="_blank" rel="noreferrer" className="news-row">
      {article.thumbnail ? (
        <img className="news-row__thumb" src={article.thumbnail} alt="" loading="lazy" />
      ) : (
        <div className="news-row__thumb news-row__thumb--empty" aria-hidden="true" />
      )}
      <div className="news-row__body">
        <p className="news-row__title">{article.title}</p>
        <span className="news-row__meta">
          {article.publisher}
          {article.publisher && article.published_at ? ' · ' : ''}
          {timeAgo(article.published_at)}
        </span>
      </div>
    </a>
  )
}

export default function NewsFeed({ articles }) {
  if (articles === null) {
    return (
      <div className="card news-feed">
        {Array.from({ length: 5 }, (_, i) => <div key={i} className="news-row news-row--loading" />)}
      </div>
    )
  }

  if (articles.length === 0) {
    return <div className="card news-feed news-feed--empty">No recent headlines for your watchlist.</div>
  }

  return (
    <div className="card news-feed">
      {articles.map((article) => (
        <NewsRow key={article.url} article={article} />
      ))}
    </div>
  )
}
