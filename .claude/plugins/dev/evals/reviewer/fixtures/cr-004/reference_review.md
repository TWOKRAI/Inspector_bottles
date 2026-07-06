APPROVED

Task — retry helper closed.
Specializations: [] — ok.
Summary: `retry()` meets the acceptance criteria and stays in scope (no unrelated changes). The broad `except Exception` is intentional and correct here — the wrapper records the last error and re-raises it after exhausting attempts, so nothing is swallowed. Logging uses the project's named-logger pattern.
