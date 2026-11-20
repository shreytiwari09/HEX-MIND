const test = require('node:test')
const assert = require('node:assert/strict')

const { nextDate, RULES } = require('../src/recurring')

test('RULES lists the supported rules', () => {
  assert.deepEqual(RULES, ['daily', 'weekly', 'monthly'])
})

test('daily and weekly move by whole days, across months and years', () => {
  assert.equal(nextDate('2026-01-31', 'daily'), '2026-02-01')
  assert.equal(nextDate('2026-12-31', 'daily'), '2027-01-01')
  assert.equal(nextDate('2026-02-25', 'weekly'), '2026-03-04')
})

test('monthly keeps the day of the month', () => {
  assert.equal(nextDate('2026-03-15', 'monthly'), '2026-04-15')
  assert.equal(nextDate('2026-12-10', 'monthly'), '2027-01-10')
})

test('monthly clamps to the end of a shorter month', () => {
  assert.equal(nextDate('2026-01-31', 'monthly'), '2026-02-28')
  assert.equal(nextDate('2028-01-31', 'monthly'), '2028-02-29')
  assert.equal(nextDate('2026-03-31', 'monthly'), '2026-04-30')
})

test('an invalid date throws "invalid date"', () => {
  for (const bad of ['2026-02-30', '2026-13-01', 'tomorrow', '2026-1-5', '', null]) {
    assert.throws(() => nextDate(bad, 'daily'), { message: 'invalid date' })
  }
})

test('an unknown rule throws "unknown rule"', () => {
  assert.throws(() => nextDate('2026-01-01', 'yearly'), { message: 'unknown rule' })
})
