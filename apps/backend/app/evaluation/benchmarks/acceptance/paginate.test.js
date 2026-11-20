const test = require('node:test')
const assert = require('node:assert/strict')

const { paginate } = require('../src/paginate')

const list = [1, 2, 3, 4, 5, 6, 7]

test('paginate returns the requested page and the totals', () => {
  assert.deepEqual(paginate(list, 2, 3), { items: [4, 5, 6], page: 2, pageSize: 3, total: 7, totalPages: 3 })
})

test('the last page may be short', () => {
  assert.deepEqual(paginate(list, 3, 3).items, [7])
})

test('a page past the end is empty but the totals stay right', () => {
  const result = paginate(list, 9, 3)
  assert.deepEqual(result.items, [])
  assert.equal(result.totalPages, 3)
})

test('an empty list has one empty page', () => {
  assert.deepEqual(paginate([], 1, 5), { items: [], page: 1, pageSize: 5, total: 0, totalPages: 1 })
})

test('invalid arguments throw', () => {
  assert.throws(() => paginate(list, 0, 3), { message: 'invalid page' })
  assert.throws(() => paginate(list, 1.5, 3), { message: 'invalid page' })
  assert.throws(() => paginate(list, 1, 0), { message: 'invalid pageSize' })
})

test('paginate does not mutate its input', () => {
  const copy = [...list]
  paginate(copy, 1, 2)
  assert.deepEqual(copy, list)
})
