# Handoff лида: plans-progress-dashboard (2026-10-02)

План: `plans/2026-10-02_plans-progress-dashboard.md` (ред. 4 + решения лида + Фаза 3). Ветка `feat/plans-progress`, worktree `.claude/worktrees/plans-progress`, HEAD `826da7769`.

## Что сделано и проверено

| Этап | Результат | Где |
|---|---|---|
| Спец-ревью текста | 3 раунда (reviewer ×2, teamlead): 7 + 4 + 3 блокера, все закрыты текстом; четвёртого раунда не было | план |
| Слепой тестер | 128 тестов, 117 красных до кода; ветка `red/plans-progress` `9f948a233` | `scripts/plans_progress/tests/` |
| Task 1.0 (teamlead) | `plans_ledger.py` читает эталон; 91 тест; ветка `feat/plans-ledger-1-0`, влита | `result-1.0.md` |
| Tasks 1.1+1.2 (developer) | `plans_progress.py`, `--json/--check/--html`; ветка `feat/plans-progress-1-1`, влита | `result-1.1.md` |
| Инъекции лида, `plans_progress` | 19/19 убиты; живой I15 (BOM) закрыт тестом `54b958972`; I03 «живой» был моим сломанным патчем | scratchpad `inject_progress.log` |
| Инъекции лида, ledger | 15/15 убиты; живые L06, L10 закрыты тестами `826da7769`; в каждой инъекции дополнительно падает тест «зеркало = источник» (мутирую зеркало) | `inject_ledger*.log` |
| Прогон | 241 passed (`scripts/plans_progress/tests`) | |

## Решения лида, которых нет в коде

- Литерал тестера `"legacy" in plans_json` исправлен на подстроку по ключам (имя плана = basename без `.md`).
- `# fmt: off` (3 строки) в источнике и зеркале ledger — обход pre-commit ruff-format (сид 88 колонок, проект 120). Альтернатива: исключить `scripts/plans_ledger.py` из ruff-format в `.pre-commit-config.yaml`. Решить при слиянии в `main`.
- PENDING по умолчанию у задач из заголовков сохранён; такие планы помечены находкой `NO_STATUS_MARK`, полем `unmarked` и чипом.

## Что не сделано

1. **Ревью кода.** `reviewer` Opus, синхронно, `run_in_background: false`, **свежий** (не re-summon: round-1 ревьюер не видел код, пусть и этот не видел). Дать: ветку, оба `result-*.md`, список мест из «Открытого». Воспроизведение «вход → вывод» обязательно.
2. **Страница глазами.** `data/plans_progress.html` собрана (387 КБ), в браузере не открывалась. Проверить светлую/тёмную тему, чип «⚠ N без отметки», раскрытие, узкий экран (claude-in-chrome, `file:///D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/plans-progress/data/plans_progress.html`).
3. **Гейт-находки ledger.** `teamlead`: 191 новая находка и 2 ушедших на реальном дереве; `approve` теперь отказывает планам с крупными phase-файлами (`TASK_TOO_BIG`); сдвиг `contract_files_fingerprint` у 10 планов. `contract.lock` в репозитории нет ни одного — утверждённые планы не ломаются. Перед слиянием в `main`: прогнать `plans_ledger.py status --check` и `approve --dry-run` (если есть) на 3 живых планах и прочитать таблицу в `result-1.0.md`.
4. **Фаза 2** (шаблон, `validate.py`, `/dev:ship`, `/dev:plan-status`, блок в `ORDER.md`) и **Фаза 3** (связи, вид «Порядок») — не начаты. Фаза 3 требует отдельного слепого тестера (граф и волны — новый механизм). Перенос в `.claude` — Фаза 2.
5. **Task 1.3** (расхождения `robot-protocol-v2`): таблица `tasks.md` даёт 5 из 21 (7 `✓`, но T-00 и PROBE вне правила id), по `ORDER.md` §2 Р выполнено 13. Отчёт ещё не написан.
6. `amendments.md` у плана нет — сдвиг fingerprint ledger не записан (teamlead не мог: файл вне FILES).
7. Слияние в `main` — только лид, по вехам; ветки `feat/plans-ledger-1-0`, `feat/plans-progress-1-1`, `red/plans-progress` и три worktree (`team-plans-ledger`, `team-plans-progress-impl`, `team-plans-progress-red`) убрать после слияния.

## agentId (адрес — id, не имя)

| Роль | agentId | Состояние |
|---|---|---|
| web-researcher (обзор готовых решений) | `a5ae9c60fc7cb5c81` | завершён |
| reviewer (спека, 2 раунда) | `a53f5e5427d3f9530` | лимит итераций исчерпан |
| teamlead (спека, раунд 3) | `a9eb5f8b22d8997b5` | завершён |
| tester (слепой, 128 тестов) | `ae90ecf68e0e71791` | завершён; можно re-summon для Фазы 3 только на тот же механизм парсинга, новый механизм (граф) — свежий |
| teamlead (Task 1.0) | `ae4f14740888447dc` | завершён |
| developer (1.1+1.2) | `aa708fe5916fb3d06` | завершён; автор — правки по ревью идут ему |

## Известные ловушки сессии

- Литералы с `\n` и `\\` в Bash-heredoc → Python съедаются слоями; файлы с экранированием писать инструментом Write.
- `git merge -F -` не читает stdin: сообщение в файл.
- `/tmp` в git-bash не виден Windows-python; временные файлы — в scratchpad.
- Рабочая копия — CRLF, индекс — LF: многострочные патчи инъекций нормализовать `.replace("\r\n","\n")`.
- Pre-commit ruff-format и trailing-whitespace перезаписывают файл и **отклоняют** первый коммит: `git add` ещё раз и коммитить заново; проверять `git log -1`.
- Для `teamlead` хук lint-brief требует DESIGN ≥3 строк, FILES ≤6, REDS; для ревью-брифа — `BRIEF-OVERRIDE: <reason>`.
