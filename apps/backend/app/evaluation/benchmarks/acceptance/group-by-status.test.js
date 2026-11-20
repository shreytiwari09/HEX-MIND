const test = require('node:test')
const assert = require('node:assert/strict')

const { groupByStatus, groupByDueDate } = require('../src/group')

const todos = [
  { id: 1, title: 'a', done: false, dueDate: '2026-02-01' },
  { id: 2, title: 'b', done: true },
  { id: 3, title: 'c', done: false, dueDate: '2026-02-01' },
  { id: 4, title: 'd', done: true, dueDate: '2026-03-01' },
]

test('groupByStatus splits open and done todos, keeping the order', () => {
  const groups = groupByStatus(todos)
  assert.deepEqual(groups.open.map((t) => t.id), [1, 3])
  assert.deepEqual(groups.done.map((t) => t.id), [2, 4])
})

test('groupByStatus on an empty list gives two empty groups', () => {
  assert.deepEqual(groupByStatus([]), { open: [], done: [] })
})

test('groupByDueDate groups by date and puts undated todos under "none"', () => {
  const groups = groupByDueDate(todos)
  assert.deepEqual(Object.keys(groups).sort(), ['2026-02-01', '2026-03-01', 'none'])
  assert.deepEqual(groups['2026-02-01'].map((t) => t.id), [1, 3])
  assert.deepEqual(groups.none.map((t) => t.id), [2])
})

test('grouping does not mutate or copy the todos', () => {
  const groups = groupByStatus(todos)
  assert.equal(groups.open[0], todos[0])
  assert.equal(todos.length, 4)
})
