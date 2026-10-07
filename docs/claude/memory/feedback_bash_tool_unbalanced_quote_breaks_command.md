---
name: feedback-bash-tool-unbalanced-quote-breaks-command
description: "Инструмент Bash на этой машине падает с «unexpected EOF while looking for matching quote», если в команде непарный апостроф — даже внутри quoted-heredoc; скрипты с прозой писать через Write и запускать файлом; также: Bash tool collapses backslashes even inside a quoted heredoc — такие файлы писать через Write/Edit"
mechanism: [windows-env]
merged_from: [feedback_bash_heredoc_collapses_backslashes]
metadata:
  node_type: memory
  type: feedback
  originSessionId: 2bef5f02-841d-4f66-86fc-b9d72ba30dce
  modified: 2026-09-02T17:53:35.760Z
---

2026-09-02, дважды за сессию: команда Bash с heredoc `<<'EOF'`, внутри которого была английская
проза с апострофами («script's», «owner's»), не выполнилась вовсе —
`bash: -c: line N: unexpected EOF while looking for matching ''`. Ни один байт heredoc не
записался, хотя quoted-heredoc по правилам bash апострофы игнорирует. Значит, обёртка
инструмента (Windows, Git Bash, PowerShell как primary shell) заворачивает команду в одинарные
кавычки до того, как bash её разбирает, и непарный `'` рвёт всю команду.

**Why:** потеря целого пакета правок за один вызов, и ошибка выглядит как синтаксическая ошибка
в скрипте, а не в транспорте — легко потратить итерацию на поиск несуществующей опечатки.

**How to apply:**
- Многострочные скрипты и файлы с прозой (комментарии, тексты правил) — писать инструментом
  `Write` в scratchpad и запускать `python <file>` / `bash <file>`. Heredoc в Bash — только для
  кода без апострофов.
- Перед отправкой команды Bash с текстом — пересчитать `'`: число должно быть чётным.
- Симптом «unexpected EOF ... matching `''» на первой же строке вывода = транспорт, не скрипт.

См. [[feedback_ru_output_encoding_and_wc]], [[feedback_commit_takes_the_whole_index]].

## Слито из feedback_bash_heredoc_collapses_backslashes (_archive/feedback_bash_heredoc_collapses_backslashes.md)

Text passed to the Bash tool loses one level of backslashes, even inside `<<'EOF'`. A Python
heredoc that writes `b"\\xff"` or `"\\n"` into a file produces the actual byte / newline, not the
escape: ruff then reports `bytes can only contain ASCII`, or a generated script dies with
`unterminated string literal`.

**Why:** hit three times on 2026-09-29 (code_reader Ф6): a test fixture byte literal, an
injection script with `"\n"` anchors, a second injection script — each cost a retry.

**How to apply:** any file or snippet that must contain a literal backslash goes through the
Write/Edit tools, not a Bash heredoc. Inside a Bash-run Python snippet, build it with `chr(92)`
or `NL = "\n"`-free concatenation (`"a" + chr(10) + "b"`). State this trap in subagent briefs
(TRAPS line) — agents hit it too. Related: [[feedback-bash-tool-unbalanced-quote-breaks-command]].
