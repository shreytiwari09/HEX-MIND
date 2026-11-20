function createNotes() {
  return { notes: [], nextId: 1 }
}

function cleanTags(tags) {
  const seen = []
  for (const raw of tags || []) {
    const tag = String(raw).trim().toLowerCase()
    if (tag && !seen.includes(tag)) seen.push(tag)
  }
  return seen
}

function addNote(store, { title, body = '', tags = [] }) {
  const clean = String(title || '').trim()
  if (!clean) throw new Error('title required')
  const note = { id: store.nextId++, title: clean, body: String(body), tags: cleanTags(tags) }
  store.notes.push(note)
  return note
}

function getNote(store, id) {
  return store.notes.find((n) => n.id === id) || null
}

function deleteNote(store, id) {
  const index = store.notes.findIndex((n) => n.id === id)
  if (index === -1) return false
  store.notes.splice(index, 1)
  return true
}

function listNotes(store) {
  return [...store.notes].sort((a, b) => a.id - b.id)
}

module.exports = { createNotes, addNote, getNote, deleteNote, listNotes }
