const round2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100

function createLedger() {
  return { expenses: [] }
}

function addExpense(ledger, { amount, category, date, note = '' }) {
  if (typeof amount !== 'number' || !(amount > 0)) throw new Error('amount must be positive')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) throw new Error('invalid date')
  const expense = {
    id: ledger.expenses.length + 1,
    amount,
    category: String(category).trim().toLowerCase(),
    date,
    note
  }
  ledger.expenses.push(expense)
  return expense
}

function totalsByCategory(ledger) {
  const totals = {}
  for (const e of ledger.expenses) totals[e.category] = (totals[e.category] || 0) + e.amount
  for (const key of Object.keys(totals)) totals[key] = round2(totals[key])
  return totals
}

function monthlyTotal(ledger, month) {
  return round2(ledger.expenses.filter((e) => e.date.startsWith(month + '-')).reduce((s, e) => s + e.amount, 0))
}

module.exports = { createLedger, addExpense, totalsByCategory, monthlyTotal }
