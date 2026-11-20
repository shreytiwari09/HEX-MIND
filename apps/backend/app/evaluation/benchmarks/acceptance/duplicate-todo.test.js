const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo, duplicateTodo } = require('../src/todos')

test('duplicateTodo appends a reopened copy with the next id', () => {
  const todos = toggleTodo(addTodo(addTodo([], 'a'), 'b'), 1)
  const copied = duplicateTodo(todos, 1)
  assert.equal(copied.length, 3)
  assert.deepEqual([copied[2].id, copied[2].title, copied[2].done], [3, 'a (copy)', false])
})

test('duplicateTodo keeps the other fields of the original', () => {
  const todos = [{ id: 4, title: 'x', done: true, dueDate: '2026-01-02', tags: ['a'] }]
  const copy = duplicateTodo(todos, 4)[1]
  assert.equal(copy.dueDate, '2026-01-02')
  assert.deepEqual(copy.tags, ['a'])
  assert.equal(copy.id, 5)
})

test('duplicateTodo with an unknown id returns an equal new array', () => {
  const todos = addTodo([], 'a')
  const result = duplicateTodo(todos, 99)
  assert.deepEqual(result, todos)
  assert.notEqual(result, todos)
})

test('duplicateTodo does not mutate its input', () => {
  const todos = addTodo([], 'a')
  duplicateTodo(todos, 1)
  assert.equal(todos.length, 1)
})
