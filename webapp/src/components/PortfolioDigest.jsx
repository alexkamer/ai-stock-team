import './PortfolioDigest.css'

function formatGeneratedAt(isoDate) {
  const date = new Date(isoDate)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const CITATION_PATTERN = /\[(\d+)\]/g

/** Splits text on `[N]` citation markers and renders each one that matches a
 * known source as a superscript link jumping to that source in the Sources
 * list below - an unrecognized/invented number is left as plain text. */
function renderWithCitations(text, sourcesByIndex) {
  const parts = []
  let lastIndex = 0
  let match
  while ((match = CITATION_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const index = Number(match[1])
    if (sourcesByIndex.has(index)) {
      parts.push(
        <sup key={match.index}>
          <a className="portfolio-digest__citation" href={`#digest-source-${index}`}>
            {index}
          </a>
        </sup>
      )
    } else {
      parts.push(match[0])
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

/** The Daily Digest tab's content - an LLM-written article on how the
 * portfolio performed today and why, plus what to watch next. Unlike every
 * other tab on this page, this is never fetched automatically: it's a real
 * Bedrock call (unlike the plain data fetches elsewhere here), so it only
 * ever runs when the user clicks the button - see PortfolioOverview's
 * digest state, which starts at `null` and stays there until then. */
export default function PortfolioDigest({ digest, onGenerate }) {
  if (digest === 'loading') {
    return (
      <div className="card portfolio-digest portfolio-digest--loading">
        <p>Writing today's digest…</p>
      </div>
    )
  }

  if (digest?.error) {
    return (
      <div className="card portfolio-digest portfolio-digest--empty">
        <p className="portfolio-digest__error">Couldn't generate a digest: {digest.error}</p>
        <button type="button" onClick={onGenerate}>
          Try again
        </button>
      </div>
    )
  }

  if (!digest) {
    return (
      <div className="card portfolio-digest portfolio-digest--empty">
        <p>
          Get a written breakdown of how your portfolio did today, why, and what to watch next - generated on
          demand, not automatically, since each one is a real AI call.
        </p>
        <button type="button" onClick={onGenerate}>
          Generate Daily Digest
        </button>
      </div>
    )
  }

  const sourcesByIndex = new Map((digest.sources ?? []).map((source) => [source.index, source]))

  return (
    <div className="card portfolio-digest">
      <div className="portfolio-digest__header">
        <h3 className="portfolio-digest__headline">{digest.headline}</h3>
        <button type="button" className="portfolio-digest__regenerate" onClick={onGenerate}>
          Regenerate
        </button>
      </div>
      {digest.generated_at && (
        <span className="portfolio-digest__generated-at">Generated {formatGeneratedAt(digest.generated_at)}</span>
      )}

      {digest.article.split('\n\n').map((paragraph, i) => (
        <p key={i} className="portfolio-digest__paragraph">
          {renderWithCitations(paragraph, sourcesByIndex)}
        </p>
      ))}

      {digest.key_drivers?.length > 0 && (
        <div className="portfolio-digest__section">
          <span className="eyebrow">Key drivers</span>
          <ul>
            {digest.key_drivers.map((item, i) => (
              <li key={i}>{renderWithCitations(item, sourcesByIndex)}</li>
            ))}
          </ul>
        </div>
      )}

      {digest.watch_items?.length > 0 && (
        <div className="portfolio-digest__section">
          <span className="eyebrow">Watch for</span>
          <ul>
            {digest.watch_items.map((item, i) => (
              <li key={i}>{renderWithCitations(item, sourcesByIndex)}</li>
            ))}
          </ul>
        </div>
      )}

      {digest.sources?.length > 0 && (
        <div className="portfolio-digest__section">
          <span className="eyebrow">Sources</span>
          <ol className="portfolio-digest__sources">
            {digest.sources.map((source) => (
              <li key={source.index} id={`digest-source-${source.index}`}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>{' '}
                &mdash; {source.publisher}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
