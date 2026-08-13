import Skeleton from './Skeleton'

/** `rows` × `<tr>` of skeleton cells, for a table body whose real headers
 * are already rendered - keeps the column structure visible immediately
 * instead of the whole table popping in once data arrives. */
export default function SkeletonRows({ columns, rows = 6, widths }) {
  return Array.from({ length: rows }).map((_, r) => (
    <tr key={r}>
      {Array.from({ length: columns }).map((_, c) => (
        <td key={c}>
          <Skeleton width={widths?.[c] ?? '70%'} />
        </td>
      ))}
    </tr>
  ))
}
