# Ревью спек волны 2 фазы 5 (стадия 0) — 5.2 / 5.3 / 5.4

Ревьюер Opus (agentId `a6267fc79dbcdffc7`, 210k, 36 вызовов, 9.5 мин), синхронно, `MODE: plan`, на `feat/transport-f5` HEAD `cdee7e03b`. Записано лидом по отчёту; правки в `phase-5.md` ещё НЕ внесены.

**VERDICT: 5.2 CHANGES REQUESTED / 5.3 CHANGES REQUESTED / 5.4 CHANGES REQUESTED**

## 5.3 — блокеры
1. Acceptance «равен ровно» (`build_gap`, ~:123) не содержит `sources`, а Дизайн говорит, что `sources` есть всегда. Замена: `{..., reasons: {"lag":2,"stale_restore":1}, sources: {"<узел>":3}, source: "<узел>"}`; ключей `reason`, `trace_id`, `capture_ts`, `frame_id` в записи с count>1 нет; `camera_id` — если один у всех.
2. ~:126 `total_not_inspected += count` проверяет код 5.2 — в worktree 5.3 красная. Замена: «`robot_control.process` вызван 1 раз; `data` дошёл с `count`/`trace_ids`/`first`/`last` без изменений». `+= count` — в 5.2 и на точке слияния.
3. Пересечение файлов: меняемый кейс 4.7d-4 лежит в `Plugins/control/robot_control/tests/test_t47d4_marker_policy.py:377` (Files 5.2). С одним маркером `robot.calls == 1` верно — убрать пункт из 5.3; новый тест «1 вызов на запись» — новый файл `process_module/tests/test_t53_*.py` со spy-плагином `accepts_markers=True`.
4. Набор ключей `build_marker` не решён (Files «`is_marker` принимает count» / Дизайн «без изменений» / меняемые тесты «дополняется count» / дверь «полный набор»). Решение: `build_marker` = сегодняшние ключи + `"count": 1`; дверь = `build_gap([build_marker(...)])[0]`; литерал записи count=1 целиком.
5. Нет правила чанка, когда вход — запись: запись неделима (`reasons` по id не делится). Правило: вход неделим, входы упаковываются жадно, пока сумма ≤ `GAP_CHUNK`. Acceptance: `build_gap([rec(1500), m])` → 2 записи, 1500 и 1.

## 5.3 — major/minor
- `capture_ts` может быть `None` (`build_marker` пишет `meta.get("capture_ts")`) → min/max по не-None; все None → `None`.
- «Риг 4.7d-2 198/250/295» есть только в `docs/claude/pilot-company-v2.md:38` — описать риг явно (узлы, N кадров, литералы).
- «Память O(1) на разрыв» неверно: `trace_ids` O(N), ≈35 Б/id. Замена: «сообщений ⌈N/1500⌉; ≈35 Б на trace_id против 255 Б на маркер».
- «Приёмник не блокируется» → `overload_events == 0`, все 1000 приняты за ≤ 2 с; «поля целы» → перечислить ключи.

## 5.2 — блокеры
1. «В планировщике ровно 1 запись» наблюдать нечем: добавить `pending() -> int`; конструктор `ActuationScheduler(fire, *, clock=time.time, tolerance_s=0.020)`; атрибут плагина `_scheduler`; ключи `cmd_get_stats` литералами: `actuation_fired_items`, `actuation_missed_items`, `actuation_late_fires`, `actuation_unscheduled_items`.
2. Acceptance «цель с now > fire_at + tolerance не стреляет» противоречит Дизайну (поздний `tick()` стреляет с `late_fires`). Замена: «`schedule()` при `now > window_end + tol` → `"missed"`, `missed_items == 1`, `pending() == 0`. Цель, поставленная вовремя, при позднем `tick()` стреляет, `late_fires == 1`».
3. Маркеры старой формы (5.3 в worktree 5.2 нет): `count = item.get("count", 1)`; `first = item.get("first_capture_ts", item.get("capture_ts"))`, `last` так же. Литерал записи из acceptance 5.3 — фикстура тестера 5.2.
4. Учёт по trace_id: `write_event` берёт `trace_id` из `unit` (`plugins/base.py:356-386`); у записи count>1 его нет → 5.6 «кадры − строки = 0» и поимённость ломаются. Нужно решение: широкая запись несёт `trace_ids` и `count`, 5.6 считает Σ count.

## 5.2 — major/minor
- Значения `actuation`: `schedule()` → `scheduled|missed|unscheduled`; при `transit_ms=0` → `immediate`. Планируется только reject; pass и маркер с pass в очередь не ставятся.
- Один термин: `missed_actuation` vs `missed_items` — оставить один.
- Out of scope «зовёт тот же `fire`, что сегодня пишет вердикт» противоречит решению 6 → «`fire` пишет только счётчики; вердикт пишется на решении».
- Меняемые тесты: кейс тайминга — `test_t47d4_marker_policy.py:274`; в `test_plugin.py` кейса тайминга обычного брака нет; `test_plugin.py:225-242` (`cmd_set_delay`) зависит от решения про алиас; `test_verdict_documents` → «без изменений».
- Алиас: `effective_transit = transit_ms or reject_delay_ms`, читать на каждом вызове; WARNING один раз на процесс с текстом `reject_delay_ms`; решить, что пишет `cmd_set_delay`.
- Воркер: сигнатура `run_loop(stop_event, pause_event)` (как `PipelineExecutor.run`), способ пробуждения, судьба heap на stop (счётчик); `ctx.worker_manager is None` (юниты) → воркер не стартует, `tick()` руками.
- ADR и общие файлы: писатели НЕ запускают `scripts.sync` (переписывает `multiprocess_framework/DECISIONS.md`, файл 5.3). ADR 5.2 → `process_module/DECISIONS.md`; правка ADR-116 для 5.4 → `process_manager_module/DECISIONS.md`; sync, README/STATUS `process_module`, галочки — лид на слиянии.
- Мелочи: `robot_control/README.md` нет — есть `readme.txt`; блока robot_control в `TEMPLATE.yaml` нет (только комментарий :61); страж принимает корень (`tmp_path`), не пишет в `Plugins/`; AST на HEAD: 2 попадания `robot_control/plugin.py:198,240`; «вердиктов по кадрам» → «широких записей решателя по кадрам».

## 5.4 — блокеры
1. Позиционная ловушка: шестой позиционный параметр `run_process_function` — `new_session` (`process_runner.py:252`); событие в `args=(...)` попадёт туда молча. Передавать `kwargs={"system_ready_event": ...}` рядом с `parent_pid`, параметр keyword-only.
2. Нет теста настоящего spawn (главный риск — пиклинг на Windows). Acceptance: «spawn-ребёнок через `ProcessRegistry` получает тот же Event; до `set()` — 0 кадров, после — кадры идут».

## 5.4 — major/minor
- Назвать атрибут экземпляра, который ставит runner. Запретить `attach_ready_event` (PM на :324-325 им объявляет свою готовность). Acceptance: ребёнок готов, событие не взведено, пока его не взведёт PM.
- Ожидание видит стоп: стоп во время preroll → поток выходит за ≤ 0.1 с, без `produce()` и без WARNING; инъекция «ожидание не видит stop_event».
- У `SourceProducer` нет колбэка warning (`log_info`/`log_error`/`log_debug`, :54-56) — назвать, какой получает текст `preroll`.
- `multi_camera.yaml` в acceptance — «после 5.9a».
- Источник `preroll_timeout_s` — константа или ключ конфига; ждать `Event.wait`, не опросом.
- Риск: готовность ≠ темп — ленивая загрузка модели в первом `process()` даст вытеснения после ready.

## Открыто (ревьюер)
- Тесты не запускал; всё — чтение и одна AST-проверка.
- Ждёт ли `_wait_boot_ready` готовности детей, требующей кадра (риск взаимной блокировки до таймаута).
- Переносит ли `_build_item` `capture_ts` в item решателя (от этого зависит 5.2).
- Spawn-передача Event, которую PM сам получил наследованием.
- Полей `Module contract:`/`Handoff:`/`Gate:` в задачах нет — применимость правила Task 3.5 не оценивалась.
