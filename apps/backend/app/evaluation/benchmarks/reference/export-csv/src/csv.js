function quote(value) {
  const text = String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function toCsv(todos) {
  const rows = todos.map((t) => [t.id, quote(t.title), t.done ? 'true' : 'false'].join(','))
  return ['id,title,done', ...rows].join('\n')
}

function parseRows(text) {
  const rows = []
  let row = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"'
        i += 1
      } else if (ch === '"') {
        quoted = false
      } else {
        field += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(field)
      field = ''
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i += 1
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += ch
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

function fromCsv(text) {
  const [, ...rows] = parseRows(text)
  const todos = []
  for (const [id, title, done] of rows) {
    const numeric = Number(id)
    if (!Number.isInteger(numeric) || title === undefined || (done !== 'true' && done !== 'false')) continue
    todos.push({ id: numeric, title, done: done === 'true' })
  }
  return todos
}

module.exports = { toCsv, fromCsv }
