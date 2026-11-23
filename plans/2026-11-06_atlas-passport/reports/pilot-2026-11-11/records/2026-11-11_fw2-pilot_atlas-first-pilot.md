## nav_bench: fw2-pilot / atlas-first-pilot (2026-11-11)

repo_sha набора `1e085652f6a7a5b3825f87157769be6de47ad928`, прогон в чистой копии `/private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx80000gn/T/nav_bench/1e085652f6a7a5b3825f87157769be6de47ad928-7d1bf96f8d`, модель `haiku`

| # | hits | файл (справка) | false | факты | hits (все) | вызовы | контекст | накоп. | cache read | сек | ходы | статус | заметки |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2/6 | 3/6 | 1 | 0/0 | 2/6 | 69 | 93584 | 103055 | 4233590 | 261.426 | 70 | success | ходов больше max_turns; нарушений доступа: 45 |
| 2 | 2/6 | 3/6 | 1 | 0/0 | 2/6 | 42 | 116616 | 110042 | 2503482 | 155.95 | 43 | success | нарушений доступа: 25 |
| 3 | 3/6 | 6/6 | 3 | 0/0 | 3/6 | 68 | 114391 | 112046 | 4935898 | 227.113 | 69 | success | ходов больше max_turns; нарушений доступа: 45 |
| **min** | 2 | | 1 | н/д | | 42 | 93584 | 103055 | 2503482 | 155.95 | | | |
| **median** | 2 | | 1 | н/д | | 68 | 114391 | 110042 | 4233590 | 227.113 | | | |
| **max** | 3 | | 3 | н/д | | 69 | 116616 | 112046 | 4935898 | 261.426 | | | |

вердикт — только hits по правилу V3; `файл` — справка

**Вердикт: TAINTED**
- нарушения доступа (115), прогон недействителен: bash-chain:python /private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869; bash-pattern:grep -r "MAX_STOP_WINDOW_KEY\|max_stop_window" --include="*.py" | head -20; bash-pattern:grep -r "class.*Blueprint\|class.*Config.*Schema\|@register_schema" --include="*; bash-pattern:grep -rn "max_stop_window_s\|max_stop_window" --include="*.py" multiprocess_fram; bash-pattern:find multiprocess_framework/modules/app_module -name "*.py" | xargs grep -l "reg
- false: 3 (порог 99) — ok

| вопрос | оценивается | #1 | #2 | #3 |
|---|---|---|---|---|
| G1 | да | miss | miss | false |
| G3 | да | miss | hit | hit |
| G5 | да | miss | miss | hit |
| G7 | да | false | false | false |
| G9 | да | hit | miss | hit |
| G11 | да | hit | hit | false |
