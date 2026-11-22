# Handoff · Н2 сим-аудит GUI → перенос на Windows (2026-11-22, конец дня на MacBook)

Предыдущий handoff (стенд, снятие пунктов 2–8): `2026-11-22_sim-audit-gui-handoff.md`. Отчёт полосы: `docs/reports/2026-11-22_sim-audit-gui.md`. Ответы владельцу по-русски.

## Что запушено (ветки на origin)
| Ветка | Что | Состояние |
|---|---|---|
| `test/sim-audit-gui` | отчёт полосы, 27 заявок в `plans/queue/inbox/` (26 находок + `_27` сводная строка очереди по корневым дефектам Р2), `wire_audit --layout-system` (код + 24 приёмочных + 35 hazard тестов), урок в память, этот handoff | ревью `wire_audit` APPROVED (раунд 2), 272 теста зелёные. Растёт от `e4443c487`; ветка `test/sim-wire-audit` (в worktree `--lane-sim-audit`) ушла на 1 доккоммит (`de0106351`, промпт полосы) — при слиянии объединить |
| `chore/qt-mcp-probe-hook` | проба qt-mcp в `gui`: один путь `QT_MCP_PROBE=1`/`QT_MCP_PORT`, пин сервера в `plugin.json`, тесты (25), правки README/`.rules/gui.md` | ревью APPROVED (раунд 2 из 2). НЕ сделана живая проверка окна + ping (строка `qt-mcp probe installed on localhost:` в логе `gui`) |
| `chore/deps-py314` | Python 3.14, `pygame` снят (решение владельца), `pytest-timeout` в dev, `uv.lock` пересобран | полный прогон тестов НЕ завершён (см. ниже); слияние только после сравнения с базой и через координатора |
| `feat/pult-belt-speed` | `VfdClient.run()` без частоты стартует на последней заданной, `belt_freq` в двух рецептах | 737 тестов зелёные; ревью стадии 5 НЕ было; на реальном ПЧ запуск — решение владельца |

В `main` ничего не сливалось и не пушилось (слияние только через координатора `inspector-bottles-95 [3d753e]`: `machine_gate.sh merge-begin/merge-end`).

## Что НЕ запушено / живёт только на MacBook
- Локальный `.mcp.json` (в `.gitignore`): запись `qt-mcp` = `uvx --from git+https://github.com/0xCarbon/qt-mcp@24303a69d498417dfcec0223bfaa95964f788c17 --with "mcp<2" qt-mcp`. Теперь она есть и в версионируемом `.claude/plugins/mcp-qt/.claude-plugin/plugin.json` (ветка qt-mcp): на Windows перегенерировать `.mcp.json` из манифеста или вписать вручную. Установка пробы в venv приложения: `pip install "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp@24303a69d498417dfcec0223bfaa95964f788c17"`.
- Логи полного прогона тестов на 3.14 (scratchpad Mac, не в git). Числа ниже.
- Venv на 3.14 (scratchpad), стенд сима и прототипа: остановлены или остановить; `stand.lock` снят.

## Полный прогон тестов на Python 3.14 (НЕЗАВЕРШЁН)
Дерево `chore/deps-py314`, venv из `uv export` без `pygame` + `pytest-timeout`. Получено до остановки: фреймворк `341 failed, 14203 passed, 54 skipped, 2 xfailed, 10 errors` (23 мин); Services `238 failed, 7768 passed, 39 skipped` (14 мин); Plugins и прототип — не завершены. Базовый прогон на 3.12 тем же способом — НЕ снят, поэтому красные нельзя назвать регрессиями (на macOS часть красных ложная: POSIX-семафоры C-93, `SharedMemory`). Три теста `layer_render` красные на 3.14 и зелёные на 3.12 (подозрение на opencv 5.1, не доказано). Нужно: прогнать оба стека на Windows/Mac в окне от координатора (`machine_gate.sh heavy`), сравнить списки красных, решить по `mcp<2`/otel. Windows и Orin (torch под JetPack) проверены только метаданными.

## Что делать дальше (по порядку)
1. Живая проверка qt-mcp (окно + ping), если сессия получит доступ к GUI.
2. Полный прогон 3.14 против 3.12, отчёт `docs/reports/2026-11-22_deps-py314_test-run.md` (его не успели записать), решение по слиянию `chore/deps-py314`.
3. Передать координатору: 27 заявок `plans/queue/inbox/2026-11-22_simaudit-gui-bd_*.md` (свёртка в реестры, `C-NN` присваивает свёртка), заявки на слияние веток (`docs/handoffs/<дата>_…-merge-request.md`).
4. Ревью стадии 5 для `feat/pult-belt-speed` (`reviewer` sonnet) и слово владельца по безопасности запуска ленты на реальном ПЧ.
5. После всей практики — `cto` (Fable, явная модель `fable`): сброс breaker при успехе (per-context breaker или `record_success` без новых ошибок), считать ли «робот остановлен» поломкой, контракт ответа хаба (reason), общий взгляд. ADR для «ЗАПУСТИТЬ возвращает ленту» (решение 1B, opt-in `params.resume_action`, сброс при fault, не для робота) — код в `device_hub` (Р2).
6. Памятка-уроки (не записаны в канон): расчётные задержки команд квантованы тиком драйвера (`poll_interval_s` 0,5 с) — не ставить ожидание «≤ 0,15 с»; `nohup`+pid проверять `kill -0`; heredoc с обратными кавычками виснет в zsh — файлы через Write; `.mcp.json` в `.gitignore`; срез «последней инкарнации» по маркеру годится, только если маркер пишется в ТОТ ЖЕ файл (`LoggerManager initialized` INFO лежит в `messages.log`, не в `system.log`).

## Решения владельца этого дня
- ЗАПУСТИТЬ возвращает ленту, если она была в работе (вариант B, ADR); «Домой» — допуск «≤ такт драйвера»; при выключенном серво отказ — предупреждение + фиксация «диск ушёл» (`wire_audit --layout-system`); `qt-mcp` оставить; `cto` — после всей практики; `pygame` снять; корневые дефекты Р2 лечить причиной, не обходом (`docs/claude/memory/project_sim_audit_root_causes_not_mitigations.md`).

## Что я оставил открытым / ненадёжным
- Ветка `feat/pult-belt-speed` и `chore/deps-py314` закоммичены ради переноса, без ревью и без полного зелёного прогона.
- В коммитах `Layer:` подобран из разрешённого списка (`services, prototype`, `infra`) — проверить хуком при слиянии.
- Агентные отчёты (инъекции wire_audit, ревью, qt-mcp) лежат в `docs/reports/2026-11-22_sim-audit-gui_wire/` и `docs/reports/2026-11-22_qt-mcp-probe-fixes.md` (в ветках), промежуточные скрипты — только в scratchpad MacBook.
