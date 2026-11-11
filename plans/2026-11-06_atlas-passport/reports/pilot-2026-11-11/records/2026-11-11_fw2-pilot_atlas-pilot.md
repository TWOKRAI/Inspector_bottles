## nav_bench: fw2-pilot / atlas-pilot (2026-11-11)

repo_sha набора `1e085652f6a7a5b3825f87157769be6de47ad928`, прогон в чистой копии `/private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx80000gn/T/nav_bench/1e085652f6a7a5b3825f87157769be6de47ad928-91df93cfd0`, модель `haiku`

| # | hits | файл (справка) | false | факты | hits (все) | вызовы | контекст | накоп. | cache read | сек | ходы | статус | заметки |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5/6 | 6/6 | 1 | 0/0 | 5/6 | 66 | 118212 | 133623 | 4869357 | 258.03 | 67 | success | ходов больше max_turns; нарушений доступа: 27 |
| 2 | 4/6 | 6/6 | 2 | 0/0 | 4/6 | 39 | 140754 | 134733 | 2904746 | 150.115 | 40 | success | нарушений доступа: 7 |
| 3 | 5/6 | 6/6 | 0 | 0/0 | 5/6 | 49 | 136139 | 132047 | 3988591 | 171.765 | 50 | success | нарушений доступа: 16 |
| **min** | 4 | | 0 | н/д | | 39 | 118212 | 132047 | 2904746 | 150.115 | | | |
| **median** | 5 | | 1 | н/д | | 49 | 136139 | 133623 | 3988591 | 171.765 | | | |
| **max** | 5 | | 2 | н/д | | 66 | 140754 | 134733 | 4869357 | 258.03 | | | |

вердикт — только hits по правилу V3; `файл` — справка

**Вердикт: TAINTED**
- нарушения доступа (50), прогон недействителен: bash-pattern:find . -type f -name "*.py" | head -20; bash-pattern:ls -la; bash-pattern:find /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx80000gn/T/nav_bench/1e085652; bash-pattern:grep -n "class SystemBuilder" /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx800; bash-pattern:grep -n "def system_shutdown" /private/var/folders/qr/q5h4tcf14556l_ry9kbf0yx800
- false: 2 (порог 99) — ok

| вопрос | оценивается | #1 | #2 | #3 |
|---|---|---|---|---|
| G1 | да | hit | hit | hit |
| G3 | да | hit | hit | hit |
| G5 | да | hit | false | hit |
| G7 | да | false | false | miss |
| G9 | да | hit | hit | hit |
| G11 | да | hit | hit | hit |
