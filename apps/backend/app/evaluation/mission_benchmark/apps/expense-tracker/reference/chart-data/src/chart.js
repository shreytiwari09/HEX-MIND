function barChartData(totals) {
  const entries = Object.entries(totals || {})
  const grand = entries.reduce((sum, [, value]) => sum + value, 0)
  if (!(grand > 0)) return []
  return entries
    .map(([label, value]) => ({ label, value, percent: Math.round((value / grand) * 1000) / 10 }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
}

module.exports = { barChartData }
