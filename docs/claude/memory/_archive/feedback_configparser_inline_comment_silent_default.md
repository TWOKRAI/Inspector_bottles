---
name: feedback-configparser-inline-comment-silent-default
description: "configparser keeps an inline '# comment' as part of the value (inline_comment_prefixes=None); int('5  # seconds') fails and a broad except returns the default — the ini setting is silently ignored / configparser не отрезает inline-комментарий, широкий except молча подставляет дефолт (ini timeout)"
module: []
mechanism: [config, error-handling]
role: developer
metadata:
  type: feedback
---

`ConfigParser()` has `inline_comment_prefixes=None`: `timeout = 5  # seconds` is read as the string `'5  # seconds'`.
A loader that does `try: int(...) except (KeyError, ValueError): return DEFAULT` then silently uses the default
(reported symptom: configured 5, effective 30).

**Why:** a broad `except ValueError` turns a config error into a plausible-looking default; the bug shows only as a
wrong runtime behaviour. Atlas 2.4g.4 probe 6b, handed up as a MEMORY LESSON block by developer `a8f9d4f1fb3be2c95`.

**How to apply:** pass `inline_comment_prefixes=("#", ";")` when operators comment in ini files; allow the default
only for an absent key, and raise with path + raw value on an unparsable one. When a config value "is ignored",
print `repr()` of the raw value first.
