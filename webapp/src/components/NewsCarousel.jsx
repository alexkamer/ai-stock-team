import { useEffect, useRef, useState } from 'react'
import TickerBadge from './TickerBadge'
import './NewsCarousel.css'

function timeAgo(isoDate) {
  const published = new Date(isoDate)
  if (Number.isNaN(published.getTime())) return ''
  const minutes = Math.max(1, Math.round((Date.now() - published.getTime()) / 60000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

const AUTOPLAY_MS = 6000

/** Featured-story carousel for the homepage - a single large slide with
 * autoplay, dot indicators, and prev/next nav. Only articles with a
 * thumbnail are eligible (see Dashboard.jsx), since the slide is an
 * image-first treatment; everything else stays in the NewsFeed list. */
export default function NewsCarousel({ articles }) {
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const timerRef = useRef(null)
  const count = articles?.length ?? 0

  useEffect(() => {
    setIndex(0)
  }, [articles])

  useEffect(() => {
    if (paused || count < 2) return
    timerRef.current = setInterval(() => setIndex((i) => (i + 1) % count), AUTOPLAY_MS)
    return () => clearInterval(timerRef.current)
  }, [paused, count])

  if (articles === null) {
    return <div className="news-carousel news-carousel--loading" />
  }

  if (count === 0) return null

  const current = articles[index]

  return (
    <div className="news-carousel" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <a
        href={current.url}
        target="_blank"
        rel="noreferrer"
        className="news-carousel__slide"
        style={{ backgroundImage: current.thumbnail ? `url(${current.thumbnail})` : 'none' }}
      >
        <div className="news-carousel__scrim" />
        <div className="news-carousel__body">
          <span className="news-carousel__eyebrow">Top story</span>
          <h3 className="news-carousel__title">{current.title}</h3>
          <span className="news-carousel__meta">
            <TickerBadge ticker={current.ticker} percent={current.ticker_day_change_percent} />
            {current.publisher}
            {current.publisher && current.published_at ? ' · ' : ''}
            {timeAgo(current.published_at)}
          </span>
        </div>
      </a>

      {count > 1 && (
        <>
          <button
            type="button"
            className="news-carousel__nav news-carousel__nav--left"
            aria-label="Previous story"
            onClick={() => setIndex((i) => (i - 1 + count) % count)}
          >
            ‹
          </button>
          <button
            type="button"
            className="news-carousel__nav news-carousel__nav--right"
            aria-label="Next story"
            onClick={() => setIndex((i) => (i + 1) % count)}
          >
            ›
          </button>
          <div className="news-carousel__dots">
            {articles.map((a, i) => (
              <button
                key={a.url}
                type="button"
                className={`news-carousel__dot ${i === index ? 'news-carousel__dot--active' : ''}`}
                aria-label={`Go to story ${i + 1}`}
                onClick={() => setIndex(i)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
