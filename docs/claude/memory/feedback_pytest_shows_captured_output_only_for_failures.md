---
name: pytest-captured-output-only-for-failures
description: "Счёт предупреждений / warning count из обычного pytest-вывода скачет с 0 до N, когда тесты начинают падать: это артефакт показа captured output, не смена поведения; считай с log_cli на обеих сторонах"
mechanism: [test-infra, measurement]
role: cto
metadata:
  type: feedback
---

Never compare a count of runtime warnings (idle_sinks, emergency_log lines) between two trees
using plain `pytest -q` output. pytest prints captured stderr/log ONLY for failed tests, so a
tree where everything passes shows 0 and a tree with 6 failures x 2 managers shows 12 - the
mechanism fired identically in both.

**Why:** Task 3.2 of observability-closure (2026-09-05): the lead measured idle_sinks as
0 before / 12 after R-7(a) and treated it as a consequence of the change. With
`-o log_cli=true --log-cli-level=WARNING` the pre-change tree showed 13 launcher warnings
(console, performance_file) and 12 error-plane warnings; post-change the same per-test count,
one more sink name in the list. The commit message carries the wrong number.

**How to apply:** when a count comes from pytest output, run both sides with
`-o log_cli=true --log-cli-level=WARNING` (or `-rA`) and group by message text with
`grep -o | sort | uniq -c`; failed tests print their captured log twice (live + failure
report), so subtract the failure count. Related: [[zero-observations-looks-like-a-result]].
