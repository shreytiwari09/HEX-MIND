const { listItems } = require('./inventory')

function lowStock(store) {
  return listItems(store)
    .filter((i) => i.qty <= i.reorderAt)
    .sort((a, b) => a.qty - b.qty || (a.sku < b.sku ? -1 : 1))
}

function totalUnits(store) {
  return listItems(store).reduce((sum, i) => sum + i.qty, 0)
}

function reorderList(store) {
  return lowStock(store)
    .map((i) => ({ sku: i.sku, name: i.name, needed: Math.max(i.reorderAt * 2 - i.qty, 1) }))
    .sort((a, b) => (a.sku < b.sku ? -1 : 1))
}

module.exports = { lowStock, totalUnits, reorderList }
