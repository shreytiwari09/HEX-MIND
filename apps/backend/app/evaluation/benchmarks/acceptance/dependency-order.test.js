const test = require('node:test')
const assert = require('node:assert/strict')

const { orderByDependencies } = require('../src/deps')

const t = (id, after) => ({ id, title: `t${id}`, done: false, ...(after ? { after } : {}) })
const ids = (todos) => todos.map((x) => x.id)

test('todos without dependencies keep their order', () => {
  assert.deepEqual(ids(orderByDependencies([t(3), t(1), t(2)])), [3, 1, 2])
})

test('a todo comes after what it depends on', () => {
  assert.deepEqual(ids(orderByDependencies([t(1, [2]), t(2)])), [2, 1])
})

test('independent todos stay in their original relative order', () => {
  assert.deepEqual(ids(orderByDependencies([t(1, [4]), t(2), t(3, [2]), t(4)])), [2, 3, 4, 1])
})

test('a chain is resolved in full', () => {
  assert.deepEqual(ids(orderByDependencies([t(1, [2]), t(2, [3]), t(3)])), [3, 2, 1])
})

test('an unknown dependency throws with its id', () => {
  assert.throws(() => orderByDependencies([t(1, [9])]), { message: 'unknown dependency: 9' })
})

test('a cycle throws "cycle detected"', () => {
  assert.throws(() => orderByDependencies([t(1, [2]), t(2, [1])]), { message: 'cycle detected' })
  assert.throws(() => orderByDependencies([t(1, [1])]), { message: 'cycle detected' })
})

test('the input is not mutated and the same objects are returned', () => {
  const input = [t(1, [2]), t(2)]
  const output = orderByDependencies(input)
  assert.deepEqual(ids(input), [1, 2])
  assert.equal(output[0], input[1])
})
