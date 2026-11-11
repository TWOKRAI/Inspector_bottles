## nav_bench: fw2-pilot / shell-pilot (2026-11-11)

repo_sha набора `1e085652f6a7a5b3825f87157769be6de47ad928`, прогон в чистой копии `/private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx80000gn/T/nav_bench/1e085652f6a7a5b3825f87157769be6de47ad928-d174c55460`, модель `haiku`

| # | hits | файл (справка) | false | факты | hits (все) | вызовы | контекст | накоп. | cache read | сек | ходы | статус | заметки |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2/6 | 6/6 | 4 | 0/0 | 2/6 | 44 | 111365 | 115659 | 2975223 | 166.958 | 45 | success | нарушений доступа: 15 |
| 2 | 3/6 | 5/6 | 2 | 0/0 | 3/6 | 82 | 144474 | 147643 | 7281764 | 294.202 | 83 | error_max_budget_usd | ошибка сессии: error_max_budget_usd; ходов больше max_turns; нарушений доступа: 44 |
| 3 | 1/6 | 3/6 | 1 | 0/0 | 1/6 | 47 | 116780 | 111466 | 3006794 | 167.209 | 48 | success | нарушений доступа: 23 |
| **min** | 1 | | 1 | н/д | | 44 | 111365 | 111466 | 2975223 | 166.958 | | | |
| **median** | 2 | | 2 | н/д | | 47 | 116780 | 115659 | 3006794 | 167.209 | | | |
| **max** | 3 | | 4 | н/д | | 82 | 144474 | 147643 | 7281764 | 294.202 | | | |

вердикт — только hits по правилу V3; `файл` — справка

**Вердикт: TAINTED**
- нарушения доступа (82), прогон недействителен: bash-pattern:find /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx80000gn/T/nav_bench/1e085652; bash-pattern:grep -n "class SystemBuilder" /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx800; bash-pattern:grep -n "def system_shutdown" /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx800; bash-pattern:grep -n "system_shutdown\|system\.shutdown" /private/var/folders/qr/q5h4tcf14556; bash-pattern:grep -n "as_generic_config\|_same_config_value" /private/var/folders/qr/q5h4tcf1
- false: 4 (порог 99) — ok

| вопрос | оценивается | #1 | #2 | #3 |
|---|---|---|---|---|
| G1 | да | hit | hit | miss |
| G3 | да | false | false | hit |
| G5 | да | false | hit | false |
| G7 | да | false | false | miss |
| G9 | да | hit | hit | miss |
| G11 | да | false | miss | miss |
