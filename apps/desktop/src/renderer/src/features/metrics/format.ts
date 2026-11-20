export const usd = (value: number): string => `$${value.toFixed(value < 1 ? 3 : 2)}`
export const percent = (value: number | null): string => (value === null ? 'not measured' : `${Math.round(value * 100)}%`)
export const count = (value: number): string => value.toLocaleString('en-US')

export function duration(seconds: number | null): string {
  if (seconds === null) return 'n/a'
  if (seconds < 90) return `${Math.round(seconds)} s`
  const minutes = seconds / 60
  return minutes < 90 ? `${Math.round(minutes)} min` : `${(minutes / 60).toFixed(1)} h`
}

/** Bars are drawn relative to the largest value; a value that is not zero always shows. */
export function barWidth(value: number, max: number): number {
  if (max <= 0 || value <= 0) return 0
  return Math.max(1.5, Math.min(100, (value / max) * 100))
}
