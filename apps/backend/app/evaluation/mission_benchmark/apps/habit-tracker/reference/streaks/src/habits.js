function parseDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso))
  if (!match) return null
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const date = new Date(Date.UTC(y, m - 1, d))
  const real = date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
  return real ? date : null
}

function createHabits() {
  return { habits: [] }
}

function addHabit(store, name) {
  const clean = String(name == null ? '' : name).trim()
  if (clean === '') throw new Error('name required')
  if (store.habits.some((h) => h.name.toLowerCase() === clean.toLowerCase())) throw new Error('habit exists')
  const habit = { id: store.habits.reduce((max, h) => Math.max(max, h.id), 0) + 1, name: clean, checkIns: [] }
  store.habits.push(habit)
  return habit
}

function getHabit(store, id) {
  return store.habits.find((h) => h.id === id) || null
}

function listHabits(store) {
  return [...store.habits].sort((a, b) => a.id - b.id)
}

function checkIn(store, id, date) {
  const habit = getHabit(store, id)
  if (!habit) throw new Error('unknown habit')
  if (parseDate(date) === null) throw new Error('invalid date')
  if (habit.checkIns.includes(date)) return false
  habit.checkIns.push(date)
  habit.checkIns.sort()
  return true
}

module.exports = { createHabits, addHabit, checkIn, getHabit, listHabits, parseDate }
