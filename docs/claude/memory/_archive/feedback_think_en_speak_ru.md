---
name: think-en-speak-ru
description: Reason internally in English for reasoning quality; all user-facing output stays in Russian
metadata:
  node_type: memory
  type: feedback
  originSessionId: 77b877ec-6dd3-465d-8bae-8167860f1da7
---

Думать (internal reasoning, chain-of-thought) — **на английском** для качества рассуждений. Общаться с пользователем (chat, всё user-facing) — **на русском**.

**Why:** Пользователь явно попросил (2026-05-28): английское рассуждение даёт более качественные выводы, но он русскоязычный и читает только русский вывод. Совпадает с project CLAUDE.md language policy («Internal reasoning can be in any language — only output matters»), но это усиленная явная инструкция.

**How to apply:** Внутренний thinking-блок — English. Любой текст наружу (ответы, комментарии в коде, документация, планы, commit-trailers, кроме system-only файлов) — русский по [[../...]] language policy. Не путать: качество рассуждения ≠ язык ответа.
