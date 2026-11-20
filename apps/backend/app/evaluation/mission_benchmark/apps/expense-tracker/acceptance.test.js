const test = require('node:test')
const assert = require('node:assert/strict')
const { createLedger, addExpense, totalsByCategory, monthlyTotal } = require('../src/expenses')
const { barChartData } = require('../src/chart')

test('addExpense validates', () => {
  const l = createLedger()
  assert.throws(() => addExpense(l, { amount: 0, category: 'food', date: '2026-03-01' }), { message: 'amount must be positive' })
  assert.throws(() => addExpense(l, { amount: 'x', category: 'food', date: '2026-03-01' }), { message: 'amount must be positive' })
  assert.throws(() => addExpense(l, { amount: 5, category: 'food', date: '03/01/2026' }), { message: 'invalid date' })
  const e = addExpense(l, { amount: 5, category: '  Food ', date: '2026-03-01', note: 'lunch' })
  assert.equal(e.id, 1)
  assert.equal(e.category, 'food')
})

test('totals per category and per month are right to the cent', () => {
  const l = createLedger()
  addExpense(l, { amount: 0.1, category: 'food', date: '2026-03-01' })
  addExpense(l, { amount: 0.2, category: 'Food', date: '2026-03-15' })
  addExpense(l, { amount: 12.5, category: 'travel', date: '2026-04-02' })
  assert.deepEqual(totalsByCategory(l), { food: 0.3, travel: 12.5 })
  assert.equal(monthlyTotal(l, '2026-03'), 0.3)
  assert.equal(monthlyTotal(l, '2026-04'), 12.5)
  assert.equal(monthlyTotal(l, '2026-05'), 0)
})

test('barChartData sorts and gives shares', () => {
  assert.deepEqual(barChartData({ food: 25, travel: 50, books: 25 }), [
    { label: 'travel', value: 50, percent: 50 },
    { label: 'books', value: 25, percent: 25 },
    { label: 'food', value: 25, percent: 25 }
  ])
  assert.deepEqual(barChartData({ a: 1, b: 2 }).map((r) => r.percent), [66.7, 33.3])
  assert.deepEqual(barChartData({}), [])
  assert.deepEqual(barChartData({ a: 0 }), [])
})
