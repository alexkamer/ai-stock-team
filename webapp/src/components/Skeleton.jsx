import './Skeleton.css'

/** A shimmering placeholder bar - the building block every loading state
 * on this page composes into a real shape (a line, a table cell, a stat). */
export default function Skeleton({ width = '100%', height = '1em', className = '' }) {
  return <span className={`skeleton ${className}`} style={{ width, height }} />
}
