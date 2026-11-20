const test = require('node:test')
const assert = require('node:assert/strict')
const { createNotes, addNote, getNote } = require('./notes')

test('a note can be added and found', () => {
  const s = createNotes()
  addNote(s, { title: 'a', body: '', tags: [] })
  assert.equal(getNote(s, 1).title, 'a')
})
