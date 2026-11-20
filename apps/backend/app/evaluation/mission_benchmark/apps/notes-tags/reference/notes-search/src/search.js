const { listNotes } = require('./notes')

function searchNotes(store, text) {
  const needle = String(text).toLowerCase()
  return listNotes(store).filter(
    (n) => n.title.toLowerCase().includes(needle) || n.body.toLowerCase().includes(needle)
  )
}

function notesByTag(store, tag) {
  const key = String(tag).trim().toLowerCase()
  return listNotes(store).filter((n) => n.tags.includes(key))
}

function tagCounts(store) {
  const counts = new Map()
  for (const note of listNotes(store)) {
    for (const tag of note.tags) counts.set(tag, (counts.get(tag) || 0) + 1)
  }
  return [...counts]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
}

module.exports = { searchNotes, notesByTag, tagCounts }
