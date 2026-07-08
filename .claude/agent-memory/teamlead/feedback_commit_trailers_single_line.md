---
name: commit-trailers-single-line
description: commit-msg hook parses trailers as a contiguous block — each trailer (Why/Layer/...) must be ONE line, no wrapped continuations
metadata:
  type: feedback
---

Trailers `Why:`/`Layer:`/`Refs:`/`Risk:`/... must each be on a SINGLE line. A
multi-line trailer value silently breaks validation.

**Why:** `scripts/validate_commit/validate_commit.py::parse_message` walks
paragraphs from the end and treats the last paragraph as trailers ONLY if EVERY
line matches `key: value`. A wrapped `Why:` whose 2nd/3rd lines don't start with
`key:` makes the whole final paragraph "not all trailers" → the block is not
parsed → hook rejects with "Missing required trailers: ['Layer', 'Why']" even
though they are literally present. Cost me a rejected commit on Task 2.2.

**How to apply:** When committing via `git commit -F -` heredoc, keep each
trailer to one physical line (long `Why:` → compress, don't wrap). Body bullets
above the blank line can wrap freely; only the final trailer block is strict.
`Co-Authored-By:` is fine as the last trailer line since it also matches
`key: value`.
