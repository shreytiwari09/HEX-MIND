function createInventory() {
  return { items: [] }
}

function wholeNumber(value) {
  return Number.isInteger(value) && value >= 0
}

function addItem(store, { sku, name, qty, reorderAt } = {}) {
  const cleanSku = String(sku == null ? '' : sku).trim().toUpperCase()
  const cleanName = String(name == null ? '' : name).trim()
  if (cleanSku === '') throw new Error('sku required')
  if (cleanName === '') throw new Error('name required')
  if (store.items.some((i) => i.sku === cleanSku)) throw new Error('sku exists')
  const level = reorderAt === undefined ? 0 : reorderAt
  if (!wholeNumber(qty) || !wholeNumber(level)) throw new Error('invalid quantity')
  const item = { sku: cleanSku, name: cleanName, qty, reorderAt: level }
  store.items.push(item)
  return item
}

function getItem(store, sku) {
  const key = String(sku).trim().toUpperCase()
  return store.items.find((i) => i.sku === key) || null
}

function listItems(store) {
  return [...store.items].sort((a, b) => (a.sku < b.sku ? -1 : a.sku > b.sku ? 1 : 0))
}

function adjust(store, sku, delta) {
  const item = getItem(store, sku)
  if (!item) throw new Error('unknown sku')
  if (item.qty + delta < 0) throw new Error('insufficient stock')
  item.qty += delta
  return item.qty
}

module.exports = { createInventory, addItem, adjust, getItem, listItems }
