const { getHabit, parseDate } = require('./habits')

const DAY = 24 * 60 * 60 * 1000

function dayNumber(iso) {
  return Math.round(parseDate(iso).getTime() / DAY)
}

function habitOrThrow(store, id) {
  const habit = getHabit(store, id)
  if (!habit) throw new Error('unknown habit')
  return habit
}

function currentStreak(store, id, today) {
  const days = new Set(habitOrThrow(store, id).checkIns.map(dayNumber))
  let day = dayNumber(today)
  if (!days.has(day)) day -= 1
  let streak = 0
  while (days.has(day)) {
    streak += 1
    day -= 1
  }
  return streak
}

function longestStreak(store, id) {
  const days = [...new Set(habitOrThrow(store, id).checkIns.map(dayNumber))].sort((a, b) => a - b)
  let best = 0
  let run = 0
  days.forEach((day, i) => {
    run = i > 0 && day === days[i - 1] + 1 ? run + 1 : 1
    best = Math.max(best, run)
  })
  return best
}

function completionRate(store, id, today, days) {
  const end = dayNumber(today)
  const start = end - days + 1
  const count = new Set(habitOrThrow(store, id).checkIns.map(dayNumber))
  let inWindow = 0
  for (const day of count) if (day >= start && day <= end) inWindow += 1
  return Math.round((inWindow / days) * 100) / 100
}

module.exports = { currentStreak, longestStreak, completionRate }
