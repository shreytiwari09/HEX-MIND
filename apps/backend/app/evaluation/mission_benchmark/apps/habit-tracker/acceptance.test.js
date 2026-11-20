const test = require('node:test')
const assert = require('node:assert/strict')
const { createHabits, addHabit, checkIn, getHabit, listHabits } = require('../src/habits')
const { currentStreak, longestStreak, completionRate } = require('../src/streaks')

test('addHabit trims, requires a name and rejects duplicates ignoring case', () => {
  const s = createHabits()
  assert.throws(() => addHabit(s, '   '), { message: 'name required' })
  const h = addHabit(s, '  Read ')
  assert.deepEqual([h.id, h.name, h.checkIns], [1, 'Read', []])
  assert.throws(() => addHabit(s, 'read'), { message: 'habit exists' })
  assert.equal(addHabit(s, 'Run').id, 2)
})

test('checkIn validates the habit and the date, ignores repeats and keeps dates sorted', () => {
  const s = createHabits()
  addHabit(s, 'Read')
  assert.throws(() => checkIn(s, 9, '2026-01-01'), { message: 'unknown habit' })
  for (const bad of ['2026-02-30', '01/02/2026', '2026-1-1', '', null]) {
    assert.throws(() => checkIn(s, 1, bad), { message: 'invalid date' })
  }
  assert.equal(checkIn(s, 1, '2026-01-03'), true)
  assert.equal(checkIn(s, 1, '2026-01-01'), true)
  assert.equal(checkIn(s, 1, '2026-01-03'), false)
  assert.deepEqual(getHabit(s, 1).checkIns, ['2026-01-01', '2026-01-03'])
  assert.equal(getHabit(s, 5), null)
  assert.deepEqual(listHabits(s).map((h) => h.id), [1])
})

function habitWith(dates) {
  const s = createHabits()
  addHabit(s, 'Read')
  for (const d of dates) checkIn(s, 1, d)
  return s
}

test('currentStreak counts consecutive days ending today or yesterday', () => {
  const s = habitWith(['2026-02-26', '2026-02-27', '2026-02-28', '2026-03-01'])
  assert.equal(currentStreak(s, 1, '2026-03-01'), 4) // across the month boundary
  assert.equal(currentStreak(s, 1, '2026-03-02'), 4) // today not done yet: still alive
  assert.equal(currentStreak(s, 1, '2026-03-03'), 0) // a day was missed
  assert.equal(currentStreak(habitWith([]), 1, '2026-03-01'), 0)
})

test('longestStreak finds the longest run', () => {
  const s = habitWith(['2026-01-01', '2026-01-02', '2026-01-04', '2026-01-05', '2026-01-06'])
  assert.equal(longestStreak(s, 1), 3)
  assert.equal(longestStreak(habitWith([]), 1), 0)
  assert.equal(longestStreak(habitWith(['2026-01-09']), 1), 1)
})

test('completionRate is check-ins in the last N days over N', () => {
  const s = habitWith(['2026-01-05', '2026-01-08', '2026-01-09', '2026-01-10'])
  assert.equal(completionRate(s, 1, '2026-01-10', 7), 0.57) // 4 of the last 7 days
  assert.equal(completionRate(s, 1, '2026-01-10', 3), 1)
  assert.equal(completionRate(s, 1, '2026-01-10', 10), 0.4)
})

test('the streak functions reject an unknown habit', () => {
  const s = habitWith([])
  assert.throws(() => currentStreak(s, 7, '2026-01-01'), { message: 'unknown habit' })
  assert.throws(() => longestStreak(s, 7), { message: 'unknown habit' })
  assert.throws(() => completionRate(s, 7, '2026-01-01', 7), { message: 'unknown habit' })
})
