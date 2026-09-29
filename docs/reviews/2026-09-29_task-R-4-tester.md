# Task R-4 — независимый tester (слепая RED-приёмка), 2026-09-29

STATUS: RED подтверждён — 8 FAILED / 8 PASSED, все красные по предсказанной причине (потеря `code`/`current_rev`).

Команда: `PYTHONPATH=$PWD .venv/Scripts/python.exe -m pytest -q --tb=line -p no:cacheprovider <два файла>`

| Тест | Итог | Причина |
|---|---|---|
| A[status], A[message] | GREEN | клиент уже отдаёт status=error и message |
| A[code], A[current_rev] | RED | поля потеряны |
| B code | RED | потерян |
| B message | GREEN | текст цел |
| C | GREEN | ровно {status, message} |
| D status | GREEN | success=False уже даёт status=error |
| D code | RED | потерян |
| E message | GREEN | reason -> message работает |
| E code | RED | потерян |
| H | GREEN | {"status":"ok","rev":3} |
| F 409 | RED | сервер ответил 504-путём: тело `{"ok": false, "error": "rev mismatch"}` |
| F code, F current_rev | RED | тела нет полей |
| G | GREEN | 504 |

Отклонение от предсказания: D целиком не красный — красна только часть про `code`; `status` при success=False клиент уже выставляет верно. Тест D[status] оставлен как охранный (не даст фиксу это сломать).

Файлы (не закоммичены):
- Plugins/hub/device_hub/tests/test_error_fields_acceptance.py
- Plugins/sim/pult_web/tests/test_error_code_through_real_client_acceptance.py

## Что я интерпретировал, а не следовал
- «One test = one check»: критерии A/B/D/E разбиты на отдельные тесты по полям (A параметризован) — чтобы красные и зелёные части были видны раздельно.
- «Valid body per route parser»: маршрут форвардит любой JSON-dict как есть, взял `{"preset": {"layers": [...]}, "base_rev": 3}`.
- `_FakeSendRouter` импортирован из соседнего тест-модуля (как велел бриф «reuse»), а не скопирован: если тот файл переименуют — оба новых файла упадут на импорте.
- В F-тестах добавлена проверка `router.calls` (команда дошла до заглушки), чтобы 409/504 не получились случайно от другой ветки.

## Что я оставил открытым и что в моей работе ненадёжно
- `pytest-timeout` в `.venv` НЕ установлен (`pip list | grep timeout` пусто, есть `PytestUnknownMarkWarning` и в чужих файлах): `pytestmark = timeout(30)` — декоративный. Реальная защита от зависания только `urlopen(timeout=10)`; `plugin.shutdown` без дедлайна. Break-injection лида, который вызовет блокировку сервера, может повесить прогон.
- Не проверял, что F станет зелёным на фиксе — только RED здесь. Форма ответа F (полный dict как есть в теле) взята из `_dispatch`: `code` отдаётся «КАК ЕСТЬ», значит тело = результат клиента целиком; если фикс положит `current_rev` во вложенный ключ, F[current_rev] останется красным — тогда решать, чей контракт верный.
- Заглушка роутера возвращает конверт с `type`/`success`/`result`; поля вроде `correlation_id` не проверялись.
- Тест E[reason] использует `code="io_error"` — литерал мой, не из брифа (бриф дал только структуру).

## Раскрытие утечек
Утечек нет. `_normalize_response` (client.py 17-57) не читал: только `grep -n "def \|class "` и `sed -n 60,135p` (начало `DeviceHubClient`, тело `request()`, где `_normalize_response` лишь вызывается). `.claude/worktrees/r4-fix` не открывал. Первая попытка записи файлов через heredoc упала на синтаксисе bash и ничего не записала — файлы созданы Write.
