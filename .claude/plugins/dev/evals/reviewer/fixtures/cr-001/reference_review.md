CHANGES REQUESTED (iteration 1 of 2)

1. [db/users.py:14] [security] — Problem: `find_by_id` builds its SQL with an f-string that interpolates `user_id` directly into the query (SQL injection, CWE-89). Fix: use a parameterized query — `cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))`.
