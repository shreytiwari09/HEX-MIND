---
name: rest-api
description: Design and build small, consistent REST endpoints.
---

# REST API

- One resource per path (`/todos`, `/todos/:id`); verbs come from the HTTP method, not the path.
- Status codes: 200 read/update, 201 create (with the new resource), 204 delete, 400 invalid
  input, 401 not signed in, 403 not allowed, 404 missing, 409 conflict. Never 200 with an error body.
- Validate every input at the boundary and return one error shape: `{"error": "message"}` (plus
  `field` when one input is wrong).
- Keep handlers thin: parse and validate, call a plain function that does the work, map the
  result to a response. The plain function is what the unit tests cover.
- List endpoints take `limit` and `offset` (or a cursor) and have a default limit.
- Write the API contract (paths, bodies, status codes) in the feature's contract file before the
  handlers, and make the handlers match it exactly.
