---
name: auth-basics
description: Sign-up, login and session handling without common security mistakes.
---

# Auth basics

- Hash passwords with a slow, salted hash (argon2id, bcrypt or scrypt); never store or log a
  password, and never write your own hashing.
- Compare secrets and tokens in constant time. Use the framework's session or signed-token support.
- Login failures give one message ("wrong email or password"), never which part was wrong.
- Cookies: `HttpOnly`, `Secure` outside local development, `SameSite=Lax` or stricter.
- Check authorisation on the server for every route that changes or reads private data; hiding a
  button is not a check.
- Secrets (session keys, API keys) come from the environment, never from source files.
- Test: sign-up, duplicate sign-up, wrong password, right password, and a request without a session.
