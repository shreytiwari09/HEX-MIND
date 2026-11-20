/**
 * A todo: { id: number, title: string, done: boolean }
 * All functions are pure: they return new arrays and never mutate their input.
 */

function nextId(todos) {
  return todos.reduce((max, t) => Math.max(max, t.id), 0) + 1
}

function addTodo(todos, title) {
  return [...todos, { id: nextId(todos), title, done: false }]
}

function toggleTodo(todos, id) {
  return todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t))
}

function moveTodo(todos, id, toIndex) {
  const from = todos.findIndex((t) => t.id === id)
  if (from === -1) throw new Error('not found')
  const rest = todos.filter((_, i) => i !== from)
  const index = Math.max(0, Math.min(rest.length, toIndex))
  return [...rest.slice(0, index), todos[from], ...rest.slice(index)]
}

module.exports = { addTodo, toggleTodo, nextId, moveTodo }
