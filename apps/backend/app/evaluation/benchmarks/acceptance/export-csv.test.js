const test = require('node:test')
const assert = require('node:assert/strict')

const { toCsv, fromCsv } = require('../src/csv')

test('toCsv writes a header and one row per todo', () => {
  const text = toCsv([{ id: 1, title: 'milk', done: false }, { id: 2, title: 'eggs', done: true }])
  assert.equal(text, 'id,title,done\n1,milk,false\n2,eggs,true')
})

test('toCsv quotes titles with commas, quotes and newlines', () => {
  const text = toCsv([{ id: 1, title: 'a, "b"\nc', done: false }])
  assert.equal(text, 'id,title,done\n1,"a, ""b""\nc",false')
})

test('an empty list is only the header', () => {
  assert.equal(toCsv([]), 'id,title,done')
})

test('fromCsv reads back what toCsv wrote', () => {
  const todos = [
    { id: 1, title: 'plain', done: false },
    { id: 2, title: 'a, "quoted"\nline', done: true },
    { id: 3, title: '', done: false },
  ]
  assert.deepEqual(fromCsv(toCsv(todos)), todos)
})

test('fromCsv accepts CRLF line endings', () => {
  assert.deepEqual(fromCsv('id,title,done\r\n1,a,true\r\n'), [{ id: 1, title: 'a', done: true }])
})

test('fromCsv skips rows that are not valid todos', () => {
  const text = 'id,title,done\nx,bad,true\n2,ok,false\n3,missing\n4,maybe,yes'
  assert.deepEqual(fromCsv(text), [{ id: 2, title: 'ok', done: false }])
})
