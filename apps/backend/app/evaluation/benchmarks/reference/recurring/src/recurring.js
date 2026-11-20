const RULES = ['daily', 'weekly', 'monthly']

function parse(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso))
  if (!match) throw new Error('invalid date')
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const date = new Date(Date.UTC(year, month - 1, day))
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    throw new Error('invalid date')
  }
  return { year, month, day }
}

function format(date) {
  return date.toISOString().slice(0, 10)
}

function nextDate(iso, rule) {
  const { year, month, day } = parse(iso)
  if (!RULES.includes(rule)) throw new Error('unknown rule')
  if (rule === 'daily') return format(new Date(Date.UTC(year, month - 1, day + 1)))
  if (rule === 'weekly') return format(new Date(Date.UTC(year, month - 1, day + 7)))
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
  return format(new Date(Date.UTC(year, month, Math.min(day, lastDay))))
}

module.exports = { nextDate, RULES }
