const test = require('node:test')
const assert = require('node:assert/strict')

const { mergeTodos } = require('../src/merge')

const t = (id, title, updatedAt, extra = {}) => ({ id, title, done: false, updatedAt, ...extra })

test('todos from both sides are kept, ordered by id', () => {
  const merged = mergeTodos([t(3, 'c', 1), t(1, 'a', 1)], [t(2, 'b', 1)])
  assert.deepEqual(merged.map((x) => x.id), [1, 2, 3])
})

test('the newer version of a todo wins', () => {
  const merged = mergeTodos([t(1, 'old', 5)], [t(1, 'new', 9)])
  assert.equal(merged[0].title, 'new')
  assert.equal(mergeTodos([t(1, 'mine', 9)], [t(1, 'theirs', 5)])[0].title, 'mine')
})

test('on a tie the local version wins', () => {
  assert.equal(mergeTodos([t(1, 'local', 5)], [t(1, 'remote', 5)])[0].title, 'local')
})

test('a newer deletion removes the todo, an older one does not', () => {
  assert.deepEqual(mergeTodos([t(1, 'a', 5)], [t(1, 'a', 9, { deleted: true })]), [])
  assert.equal(mergeTodos([t(1, 'a', 9)], [t(1, 'a', 5, { deleted: true })]).length, 1)
})

test('a todo without updatedAt counts as the oldest', () => {
  const merged = mergeTodos([{ id: 1, title: 'undated', done: false }], [t(1, 'dated', 1)])
  assert.equal(merged[0].title, 'dated')
})

test('merging does not mutate the inputs or share todo objects', () => {
  const local = [t(1, 'a', 1)]
  const remote = [t(2, 'b', 1)]
  const merged = mergeTodos(local, remote)
  merged[0].title = 'changed'
  assert.equal(local[0].title, 'a')
  assert.equal(local.length, 1)
  assert.equal(remote.length, 1)
})
