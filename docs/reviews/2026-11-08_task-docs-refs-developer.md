# docs-refs: отчёт developer

STATUS: DONE_WITH_CONCERNS (см. «Открыто»)

## Часть A
Заменено `docs/claude/DECISIONS/` -> `docs/decisions/` (git grep показывал 12 вхождений в 11 файлах + 2 зеркала): ADR.template.md:51, PROJECT_CONTEXT.template.md:14,59, sync-context.md:70 (+зеркало), _stack.md:169 (plugins/core), aggregate_context/README.md:167 и render_adr.py:12 (+зеркала), module-contract/SKILL.md:223 (+зеркало).
Утверждений «глобальные ADR агрегирует aggregate_context» в этих местах нет (README и PROJECT_CONTEXT.template уже говорят, что они не индексируются), так что правка предложений не понадобилась.
`.claude/modes/_stack.md` (проектная копия): `git grep -n 'docs/claude/DECISIONS' .claude/modes/_stack.md` -> пусто (rc=1), устаревшего пути там нет.

## Часть B
- `.claude/plugins/dev/commands/pipeline.md:250` (+ зеркало): «optional Risk/Reversible/Tested/Rejected» -> «optional `Rejected:`; `Risk:`/`Reversible:`/`Tested:` are recognized, not recommended — FREEZE, see `.claude/COMMIT_GUIDE.md`».
- `.claude/plugins/dev/agents/teamlead.md:98-99` (+ зеркало): к `Risk:` и `Reversible:` добавлена та же пометка в скобках. Слова «optional» там не было: в файле стояло «require these trailers» (ещё сильнее противоречит FREEZE). См. «Интерпретации».
- `docs/claude/TOOLING_NOTES.md:67`: Risk/Reversible/Tested вынесены из «Опциональные» в «валидатор распознаёт, но не рекомендует (FREEZE, см. COMMIT_GUIDE)». Строки 81-83 (блок формата): «(опц.)» -> «(распознаётся, не рекомендуется — FREEZE)».

## Приёмка
(1) `git grep -n 'docs/claude/DECISIONS' -- . ':!plans' ':!docs/reviews' ':!docs/handoffs' ':!docs/reports'` -> пусто, rc=1.
(2) `diff` (все шесть пар, вывод пуст, rc=0):
- plugins/core/commands/quality/sync-context.md vs commands/core/quality/sync-context.md
- plugins/dev/skills/module-contract/SKILL.md vs skills/module-contract/SKILL.md
- plugins/core/scripts/aggregate_context/README.md vs scripts/aggregate_context/README.md
- plugins/core/scripts/aggregate_context/render_adr.py vs scripts/aggregate_context/render_adr.py
- plugins/dev/commands/pipeline.md vs commands/dev/pipeline.md
- plugins/dev/agents/teamlead.md vs agents/dev/teamlead.md
Пары были идентичны до правки (каждая изменилась на одинаковое число строк).
(3) `git diff --stat`: 16 файлов, 22+/22-, только перечисленные в FILES. `git diff -- '*.py'`: только строка 12 докстринга render_adr.py (в обеих копиях), `py_compile` ок.
(4) Тестов для scripts/aggregate_context нет (`git ls-files | grep -i 'aggregate.*test'` -> пусто). `scripts/validate.py` (7 с): 2 FAIL, оба «память: теги / индекс BY-MODULE». `scripts/memory/tags.py --check` показывает unknown-module/unknown-mechanism в docs/claude/memory/*.md (напр. `project_control_core_vision.md: unknown-module: 'backend_ctl'`). Файлы памяти и tags.py я не трогал, это не моя правка. Базовый прогон до правки не делал (чистое дерево на старте, но validate до правки не гонял).

## Коммит
Не коммитил (protect-branch). Пути добавлены в индекс явно. Сообщение: /private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/30ea9658-604f-4e1f-9025-e0bfbc4c42c2/scratchpad/own_docs_refs/commit-msg.txt (Layer: docs — есть в списке COMMIT_GUIDE).

## Интерпретации
- teamlead.md: слова «optional» нет, есть «require». Лид перечислил файл как известное место, поэтому я добавил пометку FREEZE к Risk/Reversible, оставив строки в списке и `Refs:`/`Rejected:` как были. Если надо было оставить файл нетронутым, откатить две строки.
- TOOLING_NOTES.md:81-83 (блок формата) правил в ту же сторону, хотя бриф называл только строку 67: там те же «(опц.)» про те же три трейлера.

## Открыто / ненадёжно
- 2 FAIL в validate.py (память) не сверены с базой до правки; вероятно уже были (теги памяти, 4.4b).
- pipeline.md весит 34.4 КБ при бюджете 32 КБ (хук doc-size-guard). Размер вырос на ~100 байт от моей правки, но превышение было и до неё; разбиение файла не входило в задачу.
- Тестов на aggregate_context нет, правка докстринга проверена только `py_compile`.
- Остальные вхождения слова «опц./optional» про Risk/Reversible/Tested вне перечисленных файлов (например, `.gitmessage`, COMMIT_GUIDE) не искал сверх команды из брифа (`.claude/agents`, `.claude/plugins/dev`, `.claude/commands/dev`, TOOLING_NOTES).

memory hits: none (скрипт search.py не запускал: команда с вычисляемым путём заблокирована в worktree)
