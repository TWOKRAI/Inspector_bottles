---
name: project_telemetry_coherence_remediation
description: "План telemetry-coherence-remediation ЗАКРЫТ (Fable 24→47/60); Фазы 1/2/3 + qt-smoke; ветка feat/telemetry-coherence-phase2 СЛИТА и ЗАПУШЕНА в main/origin (merge 13623920); follow-up W1-W5 + pre-existing P1/P2"
metadata: 
  node_type: memory
  type: project
  originSessionId: 12f5cd70-fe43-46ae-9504-c5547e3b89fe
---

Ревью двух планов телеметрии ([[project_telemetry_self_publish]], [[project_gui_telemetry_read_model]])
пайплайном Sonnet-флот → Opus кросс-срез → Fable (вердикт **24→42/60**) вскрыл долг **когерентности
частотного контракта**. Оформлен в `plans/telemetry-coherence-remediation.md` (11 задач, 3 фазы).

**Ветка:** `feat/telemetry-coherence` (от `feat/telemetry-publish-control`). Handoff:
`docs/sessions/2026-07-17-handoff-telemetry-coherence.md`.

**Фаза 1 ПОЛНОСТЬЮ ЗАКРЫТА** (все blockers Фазы 4 GUI сняты), зелёная (framework 4919 passed):
- Task 1.1 — delta-семантика `mode: merge|replace`, оживил мёртвый `update_rule`/`remove_rule`.
- Task 1.2 — `publish.tick_sec` (тик в контракте вместо захардкоженного heartbeat 5с); **ADR-PM-016**
  (один heartbeat-воркер `min(interval, tick)`, liveness-сообщение по time-gate — частота heartbeat к
  ProcessMonitor НЕ меняется).
- Task 1.3 — три плоскости частоты согласованы: heartbeat-tick → publisher-gate (**авторитет частоты**)
  → центральный троттл (**только IPC-страховка**, дефолт мягкий 0.05с). `capped_by_throttle`-флаг вместо
  auto-relax. **ADR-PM-017**.
- Task 1.4 (f64a6700) — cap-детекция на адресном per-process пути. Решение teamlead **вариант (а)
  «перехват в PM»**: и адресный, и fan-out путь driver'а идут транзитом через PM (`telemetry.broadcast`),
  адресный помечается `data["target"]`; PM детектит cap своим central-троттлом + форвардит publish одному
  ребёнку (`_send_child_command`/`send_to_process`), throttle — центрально. Прямой driver→child путь
  ретрополнен (cap на нём принципиально не детектируем). Trade-off: адресный fire-and-forward (`reached`
  0/1 вместо per-child `applied` — иначе дедлок message_processor). Вариант (б) отвергнут. ADR-PM-017 Amendment.

**Фаза 2 ЗАКРЫТА** (2026-07-17, ветка `feat/telemetry-coherence-phase2`, коммиты ff8d5745 · dc7594e6 ·
93589f7f merged bab99c10; 1486 тестов затронутых модулей + ruff/pyright чисто):
- Task 2.1 (находка B) — единая семантика пустоты throttle. Пустой `throttle: {}`/`None` в replace →
  boot-дефолты (`default_throttle_rules`), НЕ `set_rules({})`. Полная очистка — только явным маркером
  `THROTTLE_CLEAR_MARKER = "__clear__"`. **Тонкость:** дефолты передаются ТОЛЬКО декларативным путём
  (watcher/`config.reload` из файла); адресный `telemetry.reconfigure`/broadcast зовут без дефолтов →
  пустой throttle там по-прежнему снимает всё (backward-compat). Watcher инжектит `throttle` лишь когда
  секция `telemetry` в файле объявлена (иначе observability-only reload не трогает троттл).
- Task 2.2 (находка C) — assembler кладёт СЫРУЮ per-process дельту (publish-уровень) в
  `config["telemetry_override"]` (только для процессов с override); `_cmd_config_reload` файловый путь
  `deep_merge(file_publish, override)` восстанавливает overlay (boot ≡ reload).
- Task 2.3 (находка E) — `GATED_METRICS` перенесён в `configs/telemetry_publish_config.py` (ниже слоем,
  разрыв потенц. цикла), `unknown_metrics()` + WARNING в gate-сборке + `unknown_metrics` в ответе команды.
  Исполнен параллельным агентом в worktree, слит без конфликтов.

**Грабли:** 2 golden `test_build_characterization` (`phone_sketch`/`hikvision_letter_robot`) КРАСНЫЕ и на
origin/main — дифф в `orchestrator_config` (backend_ctl/replace_debounce), НЕ связан с телеметрией. Не
гоняться, отдельный тикет обновления снапшотов. Плюс: `pyqtgraph` в pyproject, но не в `.venv` → блокит
сбор `test_telemetry_chart.py`/`test_telemetry_controls.py` (нужен `uv sync`).

**Фаза 3 ЗАКРЫТА** (2026-07-18, ветка `feat/telemetry-coherence-phase2`, Sonnet+Opus ревью):
- 3.1 typed `ProcessConfig.telemetry` (убран raw-скан до model_validate; typed-поле консистентно с
  inspector/io_peek, C6 не нарушен — частые ключи ДЛЯ typed, редкие в extras). 3.3 ре-адопция covered-подписок.
  3.4 гигиена ThrottleMiddleware (prune из handle_state_delete + lazy-prune; flush отбрасывает stale).
  3.5 перенос read-model (VM+HistorySource) во `frontend_module/state/` generic + вырез legacy
  (`_connect_bindings_legacy`, `cache_snapshot`→`read_model`) — разблокирует backend_ctl 2.3.
- **3.2 ЧАСТИЧНО:** персист runtime-дельты в PM + доигрывание после `apply_topology` (broadcast) И
  `restart_process` (адресно) + аккумуляция последовательных merge (`deep_merge`). **Шаг 3 (watcher
  fan-out publish детям) ОТЛОЖЕН** — клоббер per-process override (uniform broadcast затирает overlay из 2.2).
- **Параллель:** 3.3/3.4 (developer) + 3.5 (teamlead) в worktree одновременно, auto-merge чисто (независимые файлы).
- **Ревью Фазы 3:** Sonnet нашёл HIGH (interfaces.py F822 — агент 3.5 добавил в `__all__` реэкспорт БЕЗ импорта)
  + 3 MED (restart не доигрывал; нет integ-теста apply_topology→replay; lazy-prune слепа к `interval=0`);
  Opus (APPROVE-with-nits) вскрыл персист-«последнюю-дельту» баг. Все исправлены.

**Урок (Фаза 3):** (1) агент, добавляя в `__all__` реэкспорт, может забыть сам `import` → F822 (валит
`make check`) — проверять `ruff` по interfaces.py после переноса. (2) `isolation:worktree` создаёт worktree
от УСТАРЕВШЕГО HEAD (main), не от текущей ветки — агенты сами делали `git merge --ff-only <branch-HEAD>`;
брифовать явным SHA базы. (3) sentrux free-tier проверяет 3/34 правил и НЕ включает boundary
`framework→prototype` — критичный слой-инвариант сверять прямым grep, не полагаться на `check_rules`.
(4) персист runtime-дельты должен АККУМУЛИРОВАТЬ (deep_merge), не хранить последнее wire-сообщение — иначе
respawn теряет предыдущие точечные правки (telemetry_set в merge — типичный многошаговый сценарий).

**Финальная приёмка Fable (2026-07-18):** холистическая балльная оценка всей телеметрии — **24 → 42 → 47/60**,
вердикт «цель плана достигнута, к merge готова с оговорками». 6 осей 7-8/10; +5 честная (remediation, не новая
архитектура). Vs OTel: publisher-gate+tick_sec выше типового по cap-диагностике; read-model коммерческого уровня.
Долги-follow-up (не блок merge, кроме qt-smoke): W1 watcher-fan-out publish детям (шаг 3, per-child overlay),
W2 адресные дельты не персистятся (решать с W1 до Фазы 4 GUI), W3 cap-детекция слепа к wildcard-листу правила,
W4 глобальный stale-порог throttle, W5 `GATED_METRICS` закрыт для приложений (предел универсальности конструктора),
W6 докстринг-дрифт (исправлен ccb55eb7). Плюс: `state.unsubscribe` серверная семантика (pre-existing).

**MERGE (2026-07-18):** qt-smoke закрыт (offscreen+probe 9142, 8 вкладок + read-model, 0 Qt-ошибок).
Верификация перед merge: validate ✅, framework **5010 passed**, телеметрийные прототип-тесты **137 passed**,
формальное `/code-review` 8 углов — **0 корректностных багов** (3 LOW-наблюдения в follow-up). Ветка слита в
main `git merge --no-ff` (merge-коммит **13623920**, 49 файлов +2380/−770) и **ЗАПУШЕНО в origin/main**
(2026-07-18, pre-push sentrux пройден). Merge-коммит проходит commit-msg hook (первая строка
`Merge …` в SKIP_PREFIXES).

**Pre-existing долги прототип-suite (вскрыты при merge-верификации; НЕ от ветки — падают и на main):**
- **P1:** `test_topology_dirty_indicator` / `test_topology_dirty_pipeline` (×2 папки: `frontend/tests/`,
  `frontend/widgets/tabs/pipeline/tests/`) ВЕШАЮТ headless-прогон — модальный `confirm_unsaved_changes`,
  `QDialog.exec()` блокирует без юзера. `pytest-timeout --timeout-method=signal` НЕ прерывает Qt C++
  event-loop (SIGALRM отложен). Нужен autouse-фикстур, мокающий модалку (ср. [[feedback_no_qt_popups_offscreen]]).
- **P2:** `test_system_dashboard::test_refresh_pulls_ring_history_into_series` падает: VM `history()` отдаёт
  точки, но `telemetry_chart.set_series_data` не заполняет кривую (`setData→getData()` пусто). Баг графика
  `frontend_module/widgets/telemetry_chart.py`, НЕ read-model; воспроизведён worktree'ом main.

**Урок (merge-верификация):** «тесты прототипа зелёные» из acceptance — иллюзия headless: полный
`pytest multiprocess_prototype/` НЕ проходит из-за pre-existing модалок (P1) и чарт-фейла (P2). Верифицировать
ветку — гонять РОВНО изменённые тест-файлы (`git diff --name-only main...HEAD`), а не весь suite; при «зависании»
сперва отличать модальный ханг (`exec()`, SIGALRM бессилен) от реального фейла, и решающе проверять pre-existing
через worktree main, а не деселектить вслепую.

**Дальше:** push ветки по команде владельца (pre-push sentrux); follow-up тикеты W1-W5 (W1/W2 до Фазы 4 GUI);
pre-existing P1/P2 — отдельные тикеты; затем backend_ctl (план `plans/backend-ctl-framework-module.md`).

**Урок (Фаза 1):** per-subsystem ревью НЕ видит межподсистемных стыков — Opus/Fable кросс-срез поверх флота
нашёл HIGH (throttle full-apply сносил все правила) и design-critical (heartbeat=третья неуправляемая
плоскость частоты), которые 5 подсистемных ревьюеров пропустили. Ценность многоуровневого ревью — в разных
линзах, не в повторении.

**Урок (Фаза 2 — параллель):** параллелить независимые по файлам задачи через `isolation:worktree` — 2.3
(configs+heartbeat) шла агентом одновременно с 2.1/2.2 (telemetry_reload+builtin_commands), auto-merge без
конфликтов (разные функции даже в общем builtin_commands.py). Условие: заранее свериться, что диффы не
пересекаются построчно.

**Урок (Фаза 2 — ревью вскрыло 2 бага, что зелёные тесты прятали):** ревью Sonnet→Opus (2 итерации) на
throttle boot≡reload. **Ловушка watcher-`Config`:** `Config.update` = `merge_with_defaults`/`deep_merge`
АДДИТИВЕН — удалённый/опустошённый в файле ключ (`throttle`) остаётся stale в аккумулированном `Config`.
Значит hot-reload watcher, сравнивающий/читающий из `config.get(...)`, НЕ видит удаления секции. Правильно —
читать файл СВЕЖИМ (`DataConverter.load_from_file`), как делает ручной `config.reload`. **Ловушка теста:**
юнит-тесты на свежих `Config(initial_data=...)` НЕ репрезентативны прод-watcher'у (тот держит ОДИН `Config` и
аккумулирует через `.update()`) — тест был зелёным, а прод-сброс не работал (ср. [[feedback_test_params_hide_defect_window]]).
Гонять watcher-тесты через реальный файл + перезапись. **Silent-cap на 1-м reload:** diff-гейт с сидом
`_unseen` принимал «первое наблюдение сконфигурированного throttle» за изменение и сносил runtime-дельту —
сидировать надо ФАКТИЧЕСКОЙ boot-декларацией из файла. Итог: `make_telemetry_on_reload(config_path=...)` читает
свежим, сидирует boot-значением, diff-гейт по свежей декларации (ADR-PM-017 «no silent caps» соблюдён).
