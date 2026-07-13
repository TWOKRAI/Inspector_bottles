---
name: sentrux-freetier-3rule-limit
description: sentrux check_rules (free tier) проверяет только 3 из N правил — критичные инварианты дублируй grep-тестом
metadata:
  type: feedback
---

`mcp__sentrux__check_rules` в free-режиме проверяет **до 3 правил** (сообщение `truncated: Checking up to 3 rules ... total_rules_defined: 33`). Значит `pass:true` НЕ гарантирует, что твой свежедобавленный boundary реально проверен — он мог не попасть в 3 проверяемых.

**Why:** новый `[[boundary]]` в `.sentrux/rules.toml` может быть эффективно неверифицирован check_rules, но acceptance-задачи часто требуют «check_rules чист + инвариант X».
**How to apply:** для критичного инварианта (напр. «внутри framework 0 импортов app_module») добавляй ДОП. детерминированный pytest-grep-тест (сканирует исходники, ассертит 0 нарушений) — он авторитетен и под твоим контролем. Boundary в rules.toml оставляй как документирующий + бонус-гейт. Плюс помни слепые зоны sentrux: relative-импорты не резолвятся (используй это — внутренние импорты «крыши»-модуля делай relative, чтобы boundary `framework/* → module/*` не ловил self), `*` в boundary = только имя файла, trailing `/*` = рекурсивно.
