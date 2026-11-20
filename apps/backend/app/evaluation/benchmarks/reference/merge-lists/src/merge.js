function mergeTodos(local, remote) {
  const winners = new Map()
  for (const todo of local) winners.set(todo.id, todo)
  for (const todo of remote) {
    const mine = winners.get(todo.id)
    if (mine === undefined || (todo.updatedAt || 0) > (mine.updatedAt || 0)) winners.set(todo.id, todo)
  }
  return [...winners.values()].filter((t) => !t.deleted).sort((a, b) => a.id - b.id).map((t) => ({ ...t }))
}

module.exports = { mergeTodos }
