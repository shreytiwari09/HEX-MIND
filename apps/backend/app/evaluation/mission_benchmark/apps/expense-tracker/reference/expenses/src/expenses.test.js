const test = require('node:test')
const assert = require('node:assert/strict')
const { createLedger, addExpense, totalsByCategory } = require('./expenses')

test('an expense is counted in its category', () => {
  const l = createLedger()
  addExpense(l, { amount: 2, category: 'a', date: '2026-01-01' })
  assert.deepEqual(totalsByCategory(l), { a: 2 })
})
