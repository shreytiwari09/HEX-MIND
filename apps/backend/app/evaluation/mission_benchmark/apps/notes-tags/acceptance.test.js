const test = require('node:test')
const assert = require('node:assert/strict')
const { createNotes, addNote, getNote, deleteNote, listNotes } = require('../src/notes')
const { searchNotes, notesByTag, tagCounts } = require('../src/search')

test('addNote cleans the title and the tags', () => {
  const s = createNotes()
  assert.throws(() => addNote(s, { title: '  ', body: 'x', tags: [] }), { message: 'title required' })
  const n = addNote(s, { title: '  Plan ', body: 'b', tags: [' Work', 'work', 'IDEAS', ''] })
  assert.equal(n.id, 1)
  assert.equal(n.title, 'Plan')
  assert.deepEqual(n.tags, ['work', 'ideas'])
})

test('getNote and deleteNote', () => {
  const s = createNotes()
  addNote(s, { title: 'a', body: '', tags: [] })
  addNote(s, { title: 'b', body: '', tags: [] })
  assert.equal(getNote(s, 2).title, 'b')
  assert.equal(getNote(s, 9), null)
  assert.equal(deleteNote(s, 1), true)
  assert.equal(deleteNote(s, 1), false)
  assert.deepEqual(listNotes(s).map((n) => n.id), [2])
})

test('search, by tag, and tag counts', () => {
  const s = createNotes()
  addNote(s, { title: 'Shopping list', body: 'Milk and eggs', tags: ['home', 'food'] })
  addNote(s, { title: 'Roadmap', body: 'ship the MILK feature', tags: ['work'] })
  addNote(s, { title: 'Dinner', body: 'pasta', tags: ['food', 'home', 'fun'] })
  assert.deepEqual(searchNotes(s, 'milk').map((n) => n.id), [1, 2])
  assert.deepEqual(searchNotes(s, 'PASTA').map((n) => n.id), [3])
  assert.deepEqual(notesByTag(s, 'FOOD').map((n) => n.id), [1, 3])
  assert.deepEqual(tagCounts(s), [
    { tag: 'food', count: 2 },
    { tag: 'home', count: 2 },
    { tag: 'fun', count: 1 },
    { tag: 'work', count: 1 }
  ])
})
