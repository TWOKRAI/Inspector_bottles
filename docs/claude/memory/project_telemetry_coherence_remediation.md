---
name: project_telemetry_coherence_remediation
description: Ревью телеметрии (Fable 24→42/60) + план telemetry-coherence-remediation; Фазы 1 и 2 закрыты, дальше Фаза 3 (гигиена+простота)
metadata:
  type: project
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

**Дальше:** **Фаза 3** remediation (3.1 typed ProcessConfig.telemetry · 3.2 персист runtime-дельты+fan-out ·
3.3 covered-подписки ре-адопция · 3.4 гигиена ThrottleMiddleware · 3.5 read-model во framework — разблокирует
backend_ctl 2.3). Либо Фаза 4 GUI telemetry-publish-control по приоритету владельца
([[project_priority_product_over_engine]]).

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
