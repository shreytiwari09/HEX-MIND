const test = require('node:test')
const assert = require('node:assert/strict')
const { createUserStore, register, login } = require('./auth')
const { addTodo, listTodos } = require('./userTodos')

test('a user lists the todo they added', () => {
  const s = createUserStore()
  register(s, 'a@x.io', 'longenough')
  const t = login(s, 'a@x.io', 'longenough')
  addTodo(s, t, 'x')
  assert.equal(listTodos(s, t).length, 1)
})
