import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AFTER_HOURS_COLUMNS, derivePositionRow, POSITION_COLUMNS } from './positionRow'
import SkeletonRows from './SkeletonRows'
import './PositionsTable.css'

const SKELETON_WIDTHS = ['60px', '35px', '50px', '45px', '40px', '60px', '45px', '40px', '55px', '45px', '40px']
const AFTER_HOURS_SKELETON_WIDTHS = ['50px', '40px']

function formatAfterHoursPrice(value) {
  return value == null ? '—' : value.toFixed(2)
}

function formatDollar(value) {
  if (value == null) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}`
}

function formatPercent(value) {
  if (value == null) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function signClass(value) {
  if (value == null) return ''
  return value >= 0 ? 'text-good' : 'text-critical'
}

/** Renders positions from either the per-account or combined-portfolio
 * endpoint with the same 11-column layout, sortable by any column.
 * `isLoading` keeps the real headers on screen with skeleton rows
 * underneath, instead of the whole table popping in once data arrives. */
export default function PositionsTable({ positions, isLoading = false, showAfterHours = false }) {
  const [sort, setSort] = useState({ key: 'symbol', dir: 1 })

  const rows = useMemo(() => (positions ?? []).map(derivePositionRow), [positions])
  const columns = showAfterHours
    ? [...POSITION_COLUMNS.slice(0, 3), ...AFTER_HOURS_COLUMNS, ...POSITION_COLUMNS.slice(3)]
    : POSITION_COLUMNS

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      const aMissing = av == null
      const bMissing = bv == null
      if (aMissing || bMissing) return aMissing === bMissing ? 0 : aMissing ? 1 : -1
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv) || a.symbol.localeCompare(b.symbol)
    })
  }, [rows, sort])

  function handleSort(key) {
    setSort((prev) => (prev.key === key ? { key, dir: -prev.dir } : { key, dir: 1 }))
  }

  if (!isLoading && rows.length === 0) return <p className="positions-table__empty">No positions.</p>

  return (
    <div className="positions-table__scroll">
      <table className="positions-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>
                <button type="button" onClick={() => handleSort(column.key)}>
                  {column.label}
                  {sort.key === column.key && (sort.dir === 1 ? ' ▲' : ' ▼')}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <SkeletonRows
              columns={columns.length}
              widths={
                showAfterHours
                  ? [...SKELETON_WIDTHS.slice(0, 3), ...AFTER_HOURS_SKELETON_WIDTHS, ...SKELETON_WIDTHS.slice(3)]
                  : SKELETON_WIDTHS
              }
            />
          ) : (
            sortedRows.map((row) => (
              <tr key={row.symbol}>
                <td>
                  <Link to={`/tickers/${row.symbol}`} className="positions-table__symbol">
                    {row.symbol}
                  </Link>
                  {row.description && <span className="positions-table__description">{row.description}</span>}
                </td>
                <td className="num">{row.units}</td>
                <td className="num">{row.price == null ? '—' : row.price.toFixed(2)}</td>
                {showAfterHours && (
                  <>
                    <td className="num positions-table__ah-price" title={row.extendedHoursSession === 'pre' ? 'Pre-market' : row.extendedHoursSession === 'post' ? 'After hours' : undefined}>
                      {formatAfterHoursPrice(row.extendedHoursPrice)}
                    </td>
                    <td className={`num ${signClass(row.extendedHoursChangePercent)}`}>
                      {formatPercent(row.extendedHoursChangePercent)}
                    </td>
                  </>
                )}
                <td className={`num ${signClass(row.priceChange)}`}>{formatDollar(row.priceChange)}</td>
                <td className={`num ${signClass(row.priceChangePercent)}`}>{formatPercent(row.priceChangePercent)}</td>
                <td className="num">{row.value == null ? '—' : row.value.toFixed(2)}</td>
                <td className={`num ${signClass(row.dayChangeDollar)}`}>{formatDollar(row.dayChangeDollar)}</td>
                <td className={`num ${signClass(row.dayChangePercent)}`}>{formatPercent(row.dayChangePercent)}</td>
                <td className="num">{row.costBasisTotal == null ? '—' : row.costBasisTotal.toFixed(2)}</td>
                <td className={`num ${signClass(row.gainDollar)}`}>{formatDollar(row.gainDollar)}</td>
                <td className={`num ${signClass(row.gainPercent)}`}>{formatPercent(row.gainPercent)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
