const crypto = require('node:crypto')

function createUserStore() {
  return { users: [], tokens: {} }
}

const hash = (password, salt) => crypto.scryptSync(password, salt, 32).toString('hex')

function register(store, email, password) {
  if (typeof email !== 'string' || !email.includes('@')) throw new Error('invalid email')
  if (typeof password !== 'string' || password.length < 8) throw new Error('password too short')
  const key = email.toLowerCase()
  if (store.users.some((u) => u.email.toLowerCase() === key)) throw new Error('email taken')
  const salt = crypto.randomBytes(8).toString('hex')
  const user = { id: store.users.length + 1, email, salt, hash: hash(password, salt) }
  store.users.push(user)
  return { id: user.id, email: user.email }
}

function login(store, email, password) {
  const user = store.users.find((u) => u.email.toLowerCase() === String(email).toLowerCase())
  if (!user || hash(String(password), user.salt) !== user.hash) throw new Error('invalid credentials')
  const token = crypto.randomBytes(16).toString('hex')
  store.tokens[token] = user.id
  return token
}

function userFor(store, token) {
  const id = store.tokens[token]
  const user = store.users.find((u) => u.id === id)
  return user ? { id: user.id, email: user.email } : null
}

module.exports = { createUserStore, register, login, userFor }
