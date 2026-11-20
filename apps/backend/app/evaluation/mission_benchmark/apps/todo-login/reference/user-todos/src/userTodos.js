const { userFor } = require('./auth')

function need(store, token) {
  const user = userFor(store, token)
  if (!user) throw new Error('not logged in')
  store.todos = store.todos || {}
  store.todos[user.id] = store.todos[user.id] || []
  return store.todos[user.id]
}

function addTodo(store, token, title) {
  const list = need(store, token)
  const clean = String(title).trim()
  if (!clean) throw new Error('title required')
  const todo = { id: list.length + 1, title: clean, done: false }
  list.push(todo)
  return todo
}

function listTodos(store, token) {
  return need(store, token).map((t) => ({ ...t }))
}

function toggleTodo(store, token, id) {
  const todo = need(store, token).find((t) => t.id === id)
  if (!todo) throw new Error('todo not found')
  todo.done = !todo.done
  return { ...todo }
}

module.exports = { addTodo, listTodos, toggleTodo }
