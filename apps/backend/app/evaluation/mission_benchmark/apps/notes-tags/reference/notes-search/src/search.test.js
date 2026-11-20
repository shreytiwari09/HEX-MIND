const test = require('node:test')
const assert = require('node:assert/strict')
const { createNotes, addNote } = require('./notes')
const { searchNotes } = require('./search')

test('search finds a note by its title', () => {
  const s = createNotes()
  addNote(s, { title: 'Milk', body: '', tags: [] })
  assert.equal(searchNotes(s, 'milk').length, 1)
})
