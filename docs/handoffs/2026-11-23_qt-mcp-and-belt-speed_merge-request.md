# Заявка на слияние — полоса Г (inspector-bottles-53), 2026-11-23

Две ветки, обе от `d42f188ac` (в `main` с тех пор +5 коммитов, ветки отстают: перед слиянием rebase на текущий `main`). В `main` лид ничего не коммитил и не пушил; ветки пока только локальные (в worktree `lane-g-qtmcp` и `lane-g-belt`), на origin лежат прежние версии.

| Ветка | Коммиты | Что | Проверка |
|---|---|---|---|
| `chore/qt-mcp-probe-hook` | `3e1b76dcf`, `70bb76f1b`, `83731c048` (на origin) | проба qt-mcp в `gui`: один путь `QT_MCP_PROBE=1`/`QT_MCP_PORT`, громкий отказ без падения | ревью APPROVED (раунд 2, прошлая сессия); живая проверка 2026-11-23 на Windows: строка `qt-mcp probe installed on localhost:9142` в логе `gui`, ping → `pong`, `qt_list_windows` → `MainWindow` |
| `feat/pult-belt-speed` | `c1f96f954` (на origin), `cb07bb35a` (только локально) | `VfdClient.run()` без частоты стартует на последней заданной; память: ноль не запоминается, переживает реконнект драйвера, сбрасывается успешным `reset_fault`, `stop` сохраняет; golden и пины под 5-й action `belt_freq` | ревью стадии 5, 3 раунда, APPROVED; vfd_comm + device_hub по файлам 89 passed; рецепты + golden 21 passed; мутанты: предсказания совпали |

Перед слиянием (по правилу владельца 2026-10-21, в окне `heavy`, не мной): rebase на `main`, `validate.py`, `multiprocess_prototype/backend/tests`, framework-набор; каждый красный сверить с `plans/queue/defects.md`. Я прогонял только файлы, перечисленные выше. Каталоги целиком gate переклассифицирует и пропускает (код 75), полный прогон не запускался.

Не проверено: реальный ПЧ (запуск ленты на железе — решение владельца); `DeviceManager` и живой GUI для сценариев памяти частоты; `Plugins/hub/device_hub/tests` и тесты `camera_robot`.

Для координатора: заявки `plans/queue/inbox/2026-11-23_inspector-bottles-53_{1,2,3}.md` (`_1` и `_2` исправлены в `cb07bb35a`, `_3` — backlog: пульт передаёт частоту поля явно). Hook коммита `cb07bb35a` предупредил о теме > 72 символов и об отсутствии `Decision: ADR-VC-004` (предупреждения). Отчёт: `docs/reports/2026-11-23_qt-mcp-and-belt-speed_win.md`, полный отчёт ревью — рядом, `belt_review.md`.

Слово владельца нужно на: пуш `feat/pult-belt-speed` на origin; взять ли в работу заявку про пульт.
