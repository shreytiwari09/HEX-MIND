const test = require('node:test')
const assert = require('node:assert/strict')
const { createInventory, addItem, adjust, getItem, listItems } = require('../src/inventory')
const { lowStock, totalUnits, reorderList } = require('../src/reports')

test('addItem normalises the sku and validates the fields', () => {
  const s = createInventory()
  const item = addItem(s, { sku: ' ab-1 ', name: ' Bolt ', qty: 5 })
  assert.deepEqual(item, { sku: 'AB-1', name: 'Bolt', qty: 5, reorderAt: 0 })
  assert.throws(() => addItem(s, { sku: ' ', name: 'x', qty: 1 }), { message: 'sku required' })
  assert.throws(() => addItem(s, { sku: 'A', name: ' ', qty: 1 }), { message: 'name required' })
  assert.throws(() => addItem(s, { sku: 'ab-1', name: 'x', qty: 1 }), { message: 'sku exists' })
  for (const qty of [-1, 1.5, '3', undefined]) {
    assert.throws(() => addItem(s, { sku: 'Z', name: 'x', qty }), { message: 'invalid quantity' })
  }
  assert.throws(() => addItem(s, { sku: 'Z', name: 'x', qty: 1, reorderAt: -2 }), { message: 'invalid quantity' })
  assert.equal(listItems(s).length, 1)
})

test('adjust changes the quantity and refuses to go below zero', () => {
  const s = createInventory()
  addItem(s, { sku: 'a', name: 'A', qty: 3 })
  assert.equal(adjust(s, 'A', 4), 7)
  assert.equal(adjust(s, 'a', -7), 0)
  assert.throws(() => adjust(s, 'a', -1), { message: 'insufficient stock' })
  assert.equal(getItem(s, 'a').qty, 0)
  assert.throws(() => adjust(s, 'nope', 1), { message: 'unknown sku' })
})

test('getItem ignores case and listItems is sorted by sku', () => {
  const s = createInventory()
  addItem(s, { sku: 'b', name: 'B', qty: 1 })
  addItem(s, { sku: 'a', name: 'A', qty: 1 })
  assert.equal(getItem(s, 'B').name, 'B')
  assert.equal(getItem(s, 'zzz'), null)
  assert.deepEqual(listItems(s).map((i) => i.sku), ['A', 'B'])
})

function stocked() {
  const s = createInventory()
  addItem(s, { sku: 'c', name: 'Cog', qty: 2, reorderAt: 5 })
  addItem(s, { sku: 'a', name: 'Axle', qty: 9, reorderAt: 5 })
  addItem(s, { sku: 'b', name: 'Bolt', qty: 5, reorderAt: 5 })
  addItem(s, { sku: 'd', name: 'Dial', qty: 0, reorderAt: 0 })
  return s
}

test('lowStock lists items at or below the reorder level, fewest first', () => {
  assert.deepEqual(lowStock(stocked()).map((i) => i.sku), ['D', 'C', 'B'])
})

test('totalUnits sums the quantities', () => {
  assert.equal(totalUnits(stocked()), 16)
  assert.equal(totalUnits(createInventory()), 0)
})

test('reorderList brings low items up to twice their level, at least one, sorted by sku', () => {
  assert.deepEqual(reorderList(stocked()), [
    { sku: 'B', name: 'Bolt', needed: 5 },
    { sku: 'C', name: 'Cog', needed: 8 },
    { sku: 'D', name: 'Dial', needed: 1 }
  ])
})
