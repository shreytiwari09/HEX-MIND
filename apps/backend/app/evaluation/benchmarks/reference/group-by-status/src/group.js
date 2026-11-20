function groupByStatus(todos) {
  return { open: todos.filter((t) => !t.done), done: todos.filter((t) => t.done) }
}

function groupByDueDate(todos) {
  const groups = {}
  for (const todo of todos) {
    const key = typeof todo.dueDate === 'string' && todo.dueDate !== '' ? todo.dueDate : 'none'
    ;(groups[key] = groups[key] || []).push(todo)
  }
  return groups
}

module.exports = { groupByStatus, groupByDueDate }
