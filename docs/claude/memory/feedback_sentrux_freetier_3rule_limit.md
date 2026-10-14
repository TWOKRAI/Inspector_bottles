---
name: sentrux-freetier-3rule-limit
description: "sentrux check_rules (free tier) проверяет только 3 из N правил — критичные инварианты дублируй grep-тестом; CLI sentrux check не видит импорт `from pkg import module` (цикл зелёный) / sentrux free tier rule limit; CLI blind to package-imports-module form"
mechanism: [dev-tooling, guards]
role: teamlead
metadata:
  type: feedback
---

`mcp__sentrux__check_rules` в free-режиме проверяет **до 3 правил** (сообщение `truncated: Checking up to 3 rules ... total_rules_defined: 33`). Значит `pass:true` НЕ гарантирует, что твой свежедобавленный boundary реально проверен — он мог не попасть в 3 проверяемых.

**Why:** новый `[[boundary]]` в `.sentrux/rules.toml` может быть эффективно неверифицирован check_rules, но acceptance-задачи часто требуют «check_rules чист + инвариант X».
**How to apply:** для критичного инварианта (напр. «внутри framework 0 импортов app_module») добавляй ДОП. детерминированный pytest-grep-тест (сканирует исходники, ассертит 0 нарушений) — он авторитетен и под твоим контролем. Boundary в rules.toml оставляй как документирующий + бонус-гейт. Плюс помни слепые зоны sentrux: relative-импорты не резолвятся (используй это — внутренние импорты «крыши»-модуля делай relative, чтобы boundary `framework/* → module/*` не ловил self), `*` в boundary = только имя файла, trailing `/*` = рекурсивно.

**Слепое пятно CLI `sentrux check .` — импорт «пакет → модуль» (замер 2026-10-14, layer-render 6.3).** Scratch-worktree,
файлы под `git add` (сканирует только `git ls-files`), `max_cycles` временно 0. Цикл `_cyc_a.py ↔ _cyc_b.py`, записанный
`from Services.dataset_gen._cyc_b import B` / `from Services.dataset_gen._cyc_a import A` → «✗ max_cycles: Found 1 circular
dependencies» с обоими файлами (циклы — по файлам). Тот же цикл в записи `from Services.dataset_gen import _cyc_b` →
`✓ All rules pass`: форма не резолвится, ребра нет. База репо — 0 циклов (комментарий «текущее 1» в `rules.toml:31` устарел).
Триггер: зелёный sentrux как довод «цикла/нарушения границы нет» — сначала положительный контроль в той же записи
импорта и с `git add`; в новом коде писать `from Services.<pkg>.<module> import <name>`.
