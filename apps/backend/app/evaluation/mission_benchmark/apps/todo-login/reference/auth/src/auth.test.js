const test = require('node:test')
const assert = require('node:assert/strict')
const { createUserStore, register, login, userFor } = require('./auth')

test('register, login and look up a user', () => {
  const s = createUserStore()
  register(s, 'a@x.io', 'longenough')
  assert.equal(userFor(s, login(s, 'a@x.io', 'longenough')).email, 'a@x.io')
})
