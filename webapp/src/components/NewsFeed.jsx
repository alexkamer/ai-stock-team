import { useState } from 'react'
import TickerBadge from './TickerBadge'
import { getJSON } from '../api/client'
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

function ArticleSummary({ url }) {
  const [state, setState] = useState(null) // null | 'loading' | { summary, looks_paywalled } | { error }

  if (state === null) {
    return (
      <button
        type="button"
        className="news-row__summarize"
        onClick={async (e) => {
          e.preventDefault()
          setState('loading')
          try {
            const result = await getJSON(`/articles/summary?url=${encodeURIComponent(url)}`)
            setState(result)
          } catch (err) {
            setState({ error: err.message })
          }
        }}
      >
        Summarize
      </button>
    )
  }

  if (state === 'loading') {
    return <p className="news-row__summary news-row__summary--loading">Reading article…</p>
  }

  if (state.error) {
    return <p className="news-row__summary news-row__summary--error">Couldn't summarize: {state.error}</p>
  }

  return (
    <p className="news-row__summary">
      {state.looks_paywalled && <span className="news-row__summary-flag">Article may be paywalled — </span>}
      {state.summary}
    </p>
  )
}

function NewsRow({ article, showTicker, summarizable }) {
  return (
    <div className="news-row">
      <a href={article.url} target="_blank" rel="noreferrer" className="news-row__link">
        {article.thumbnail ? (
          <img className="news-row__thumb" src={article.thumbnail} alt="" loading="lazy" />
        ) : (
          <div className="news-row__thumb news-row__thumb--empty" aria-hidden="true" />
        )}
        <div className="news-row__body">
          <p className="news-row__title">{article.title}</p>
          {article.summary && <p className="news-row__preview">{article.summary}</p>}
          <span className="news-row__meta">
            {showTicker && <TickerBadge ticker={article.ticker} percent={article.ticker_day_change_percent} />}
            {article.publisher}
            {article.publisher && article.published_at ? ' · ' : ''}
            {timeAgo(article.published_at)}
          </span>
        </div>
      </a>
      {summarizable && (
        <div className="news-row__extra">
          <ArticleSummary url={article.url} />
        </div>
      )}
    </div>
  )
}

export default function NewsFeed({ articles, showTicker = true, summarizable = false }) {
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
        <NewsRow key={article.url} article={article} showTicker={showTicker} summarizable={summarizable} />
      ))}
    </div>
  )
}
