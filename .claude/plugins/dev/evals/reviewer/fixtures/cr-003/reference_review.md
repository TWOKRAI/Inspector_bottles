CHANGES REQUESTED (iteration 1 of 2)

1. [clients/payments.py:3] [security] — Problem: a live API key is hardcoded as `API_KEY = "sk-live-..."`, committing a secret to the repo (CWE-798). Fix: load it from the environment (`os.environ["PAYMENTS_API_KEY"]`), add the name to `.env.example`, and rotate the leaked key.
2. [clients/payments.py:6] [quality] — Problem: the factory `MakeClient` is not snake_case, breaking the project naming convention. Fix: rename to `make_client`.
