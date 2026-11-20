import { barWidth } from './format'

interface Row {
  label: string
  value: number
  text: string
  note?: string
}

interface Props {
  title: string
  rows: Row[]
  empty?: string
}

/** A list of horizontal bars, drawn with plain elements so every value is also readable text. */
export function Bars({ title, rows, empty = 'Nothing yet.' }: Props) {
  const max = Math.max(0, ...rows.map((r) => r.value))
  return (
    <section className="metrics__block" aria-label={title}>
      <h3 className="mission__section-title">{title}</h3>
      {rows.length === 0 ? (
        <p className="mission__muted">{empty}</p>
      ) : (
        <ul className="bars">
          {rows.map((row) => (
            <li key={row.label} className="bars__row">
              <span className="bars__label">{row.label}</span>
              <span className="bars__track" aria-hidden="true">
                <span className="bars__bar" style={{ width: `${barWidth(row.value, max)}%` }} />
              </span>
              <span className="bars__value">
                {row.text}
                {row.note && <span className="mission__muted"> {row.note}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
