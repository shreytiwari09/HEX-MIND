const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, moveTodo } = require('../src/todos')

const three = () => addTodo(addTodo(addTodo([], 'a'), 'b'), 'c')
const ids = (todos) => todos.map((t) => t.id)

test('moveTodo moves a todo to a later position', () => {
  assert.deepEqual(ids(moveTodo(three(), 1, 2)), [2, 3, 1])
})

test('moveTodo moves a todo to an earlier position', () => {
  assert.deepEqual(ids(moveTodo(three(), 3, 0)), [3, 1, 2])
})

test('moveTodo clamps an index outside the list', () => {
  assert.deepEqual(ids(moveTodo(three(), 2, 99)), [1, 3, 2])
  assert.deepEqual(ids(moveTodo(three(), 2, -5)), [2, 1, 3])
})

test('moveTodo throws "not found" for an unknown id', () => {
  assert.throws(() => moveTodo(three(), 9, 0), { message: 'not found' })
})

test('moveTodo does not mutate its input', () => {
  const todos = three()
  moveTodo(todos, 1, 2)
  assert.deepEqual(ids(todos), [1, 2, 3])
})
