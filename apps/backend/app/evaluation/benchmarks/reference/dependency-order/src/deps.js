function orderByDependencies(todos) {
  const byId = new Map(todos.map((t, index) => [t.id, { todo: t, index }]))
  for (const todo of todos) {
    for (const dep of todo.after || []) {
      if (!byId.has(dep)) throw new Error(`unknown dependency: ${dep}`)
    }
  }
  const waiting = new Map(todos.map((t) => [t.id, new Set(t.after || [])]))
  const result = []
  while (result.length < todos.length) {
    const ready = todos.filter((t) => !result.includes(t) && waiting.get(t.id).size === 0)
    if (ready.length === 0) throw new Error('cycle detected')
    const next = ready[0]
    result.push(next)
    for (const deps of waiting.values()) deps.delete(next.id)
  }
  return result
}

module.exports = { orderByDependencies }
