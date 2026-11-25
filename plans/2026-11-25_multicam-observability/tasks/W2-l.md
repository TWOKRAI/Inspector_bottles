# Task W2-l: повреждённый кадр камеры помечен, не инспектируется как обычный, доля неполных видна в здоровье

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Module contract:** public-api-change (ключи item камеры `incomplete`, `lost_packets`; поля регистра `incomplete_policy`, `incomplete_degraded_ratio`; причина маркера `incomplete` в `MARKER_REASONS`, ADR-174)
- **Dependencies:** W2-a, W2-a1, W2-a2 (та же ветка камеры, после их коммитов: `_on_incomplete` из W2-a2 входит в знаменатель доли); W2-g — если слит раньше, база после него
- **Блокер:** решение владельца Р-W2-12 (политика повреждённого кадра и умолчание). Текст ниже — ПРЕДЛОЖЕНИЕ ЛИДА, ждёт владельца
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиусы `Services/camera_device/tests`, `multiprocess_framework/modules/router_module/tests` (medium) — новых красных нет против снимка лида
- **Files:** `Services/camera_device/plugin_base.py`, `Services/camera_device/registers_base.py`, `multiprocess_framework/modules/router_module/middleware/not_inspected_marker.py`, `multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py`, `Services/camera_device/tests/test_incomplete_policy.py`, `multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt`
- **Handoff:** lead -> teamlead (REDS в брифе: красный прогон до правки src, break-injection) -> reviewer (стадия 5, opus)

Основание — стенд 2026-11-25 (`docs/reviews/2026-11-25_stand-wave1.md`, F1-F3), дерево `mco-stand` `ea65a3334`:
- ~50 с после старта: `camera_0` `frames=567, incomplete=627, lost_packets=155521, lost_frames=326`; `camera_1` `frames=1194, incomplete=1004, lost_packets=4760`. Опыт 5 к/с: `camera_1` 0 неполных из 210, `camera_0` 208 из 211 (~248 пакетов на кадр, ~18 % пикселей). Полоски на картинке `camera_1` при `incomplete 471` из 569 подтвердил владелец.
- При этом `health.status=ok`, `degraded_reason=null`, `readiness.ready=true`, аномалий нет; в журналах `camera_0/`, `camera_1/` по `incomplete|lost_packets|lost_frames|потер|неполн` — 0 строк.

Причина в коде (проверено чтением `mco-stand`):
- `plugin_base.py:482-484` (`_on_frame`): `lost_packets > 0` только наращивает `_incomplete` и `_lost_packets`; кадр кладётся в очередь как обычный (`:494`).
- `_build_item` (`plugin_base.py:753-771`): ключа повреждения в item нет. `git grep -n lost_packets` по `Services Plugins multiprocess_prototype multiprocess_framework` вне тестов — только `interface.py`, `plugin_base.py`, `fake_port.py`, `driver.py`: дальше камеры признак не уходит.
- Здоровье меняют только `_report_incidents` (`plugin_base.py:658-671`, состояния `_FAILED` и `param_errors`) и сторож; счётчики потерь в здоровье не входят. Строк журнала о потерях нет: `_tick` (`:581-612`) только публикует уровни.
- Готовый механизм «не проверено» во framework есть: маркер `not_inspected` (`router_module/middleware/not_inspected_marker.py:26-46`, ADR-174); маркер идёт мимо плагинов без `accepts_markers` (`plugin_operation_step.py:80`, `pipeline_executor.py:246-248`, в обоих режимах `overflow`), `robot_control` применяет `not_inspected_action` (по умолчанию брак, `Plugins/control/robot_control/plugin.py:179,258-289`). Тег `inspection_status` на item с кадром `robot_control` не читает (только `is_marker`) — поэтому путь «кадр с тегом» не годится.

TASK: W2-l — кадр с потерянными пакетами несёт признак до потребителя; по политике камеры он уходит маркером «не проверено»; доля неполных кадров даёт `degraded` и строку журнала   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: lead -> you -> reviewer (стадия 5, opus)

DESIGN (decided by the lead — you type it, you do not derive it; ПРЕДЛОЖЕНИЕ до слова владельца):
  1. `registers_base.py`, `CameraDeviceRegisters`: `incomplete_policy: Literal["not_inspected", "inspect"] = "not_inspected"` (FieldMeta: «Кадр с потерянными пакетами»; `not_inspected` — кадр не инспектируется, линия применяет политику непроверенного; `inspect` — кадр идёт в обработку с признаком); `incomplete_degraded_ratio: float = 0.05` (min 0.0, max 1.0; `0` — без `degraded`). Оба — `apply="config"` (живой правки нет: читаются в `produce()`/`_tick` из `self._reg` на каждом вызове).
  2. Признак в item (`_build_item`, обе политики): `"incomplete": raw.lost_packets > 0`, `"lost_packets": raw.lost_packets`. Признак едет в `msg["data"]` (`source_producer.py:323-330`) и копируется приёмником (`data_receiver.py:523-525`).
  3. `produce()` (`plugin_base.py:689-716`): слот с `raw.lost_packets > 0` и `self._reg.incomplete_policy == "not_inspected"` -> `_build_item` НЕ зовётся (дебайер не тратится); вместо item — `build_marker({"capture_ts": ts, "frame_id": seq, "camera_id": self._reg.camera_id}, reason="incomplete", source=self._ctx.process_name)` и `marker["lost_packets"] = raw.lost_packets`. `self._frames` не растёт (маркер — не кадр); новый счётчик `self._not_inspected` (+1 под `_stats_lock`), уровень `not_inspected_incomplete` в `_tick` (и при нуле), обнуляется `reset_stats` рядом с `_incomplete` (`plugin_base.py:897`). Порядок items по `seq` не меняется.
  4. `not_inspected_marker.py:20`: `MARKER_REASONS = ("lag", "stale_restore", "stale_exec", "door", "incomplete")`; докстринг модуля: `incomplete` рождает источник (не узел при переполнении), формула приёмки ADR-174 п.5 для соседа получает слагаемое `not_inspected_incomplete` источника. Тест `test_t47d1_marker_contract.py:43` — меняется ТОЛЬКО литерал этой строки (разрешение лида).
  5. Доля и здоровье. В `_on_frame` и в `_on_incomplete` (W2-a2, короткий кадр) под `self._lock` — `self._seen += 1` (кадр, который прибор пытался отдать). `_tick` копит окно 10 с (`_INCOMPLETE_WINDOW_S = 10.0`): по закрытии окна `ratio = Δ_incomplete / Δ_seen` (`Δ_seen == 0` -> окно не судит). Одна функция `_sync_health_claim()` решает заявку плагина (у `ctx.health` один владелец — имя плагина, `health/state.py:628-657`): состояние из `_FAILED` -> прежний `degraded(f"camera_device: {state}")`; иначе `ratio >= incomplete_degraded_ratio > 0` -> `degraded(f"camera_device: неполные кадры {pct:.0f} % за 10 с")`; иначе `set_status("ok")`. Её зовут `_report_incidents` (вместо прямых `degraded`/`set_status` на `:665-667`) и `_tick`; иначе выход из `error` снимет заявку доли и наоборот.
  6. Журнал: вход в превышение — WARNING `CameraDevicePlugin: неполные кадры <pct:.0f> % за 10 с (<d_inc> из <d_seen>, потеряно пакетов <d_lost>); политика <policy>`; пока превышение длится — та же строка не чаще раза в 60 с; выход — INFO `CameraDevicePlugin: неполные кадры ниже порога: <pct:.0f> %`. Строки — вне `self._lock`.
  7. Не меняется: счёт `incomplete`/`lost_packets`/`lost_frames`/`trigger_lost` в `_on_frame`; очередь и `overwritten`; горячий путь `_on_frame` получает одно `+= 1` под уже взятым замком.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/camera_device/plugin_base.py — п.2, 3, 5, 6
  2. Services/camera_device/registers_base.py — п.1
  3. multiprocess_framework/modules/router_module/middleware/not_inspected_marker.py — п.4
  4. multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py — только литерал строки 43
  5. Services/camera_device/tests/test_incomplete_policy.py — новый, REDS и тесты опасности
  6. multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt — пересборка снимка (два новых поля)

REDS (predicted red tests; фейк `make_port(frame_meta=...)`, `fake_port.py:12,394-406`):
  - Services/camera_device/tests/test_incomplete_policy.py::test_damaged_frame_becomes_marker_by_default (кадры `frame_meta` `(1,0,None),(2,7,None),(3,0,None)` -> `produce()` дал 3 элемента: item seq 1, маркер, item seq 3; маркер: `inspection_status == "not_inspected"`, `reason == "incomplete"`, `lost_packets == 7`, `frame_id == 2`, `"frame" not in marker`; уровень `frames == 2`, `not_inspected_incomplete == 1`)
  - …::test_inspect_policy_keeps_frame_with_mark (`incomplete_policy "inspect"` -> 3 item, у второго `incomplete is True`, `lost_packets == 7`, `frame.shape` как у соседей)
  - …::test_intact_frame_carries_false_mark (`incomplete is False`, `lost_packets == 0`)
  - …::test_ratio_over_threshold_degrades_and_warns_once (20 кадров, 2 неполных за окно 10 с при пороге 0.05 -> `health.status == "degraded"`, причина `camera_device: неполные кадры 10 % за 10 с`; WARNING ровно 1 за 2 окна)
  - …::test_ratio_below_threshold_recovers_with_info (следующее окно 0 из 20 -> `ok`, одна INFO `неполные кадры ниже порога: 0 %`)
  - …::test_session_error_exit_keeps_ratio_claim (доля выше порога, сеанс `error` -> `grabbing`: статус остаётся `degraded` с причиной доли)
  - …::test_zero_ratio_threshold_never_degrades (`incomplete_degraded_ratio 0.0`, все кадры неполные -> `ok`, WARNING 0)
  - multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py::<тест строки 43> (литерал кортежа)
  - …/test_incomplete_policy.py::test_marker_passes_executor_to_marker_plugin (проводка: настоящий `PipelineExecutor` с плагином без `accepts_markers` и плагином-приёмником с `accepts_markers = True` -> приёмник получил маркер с `reason "incomplete"`, первый плагин не вызван)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short Services/camera_device/tests/test_incomplete_policy.py multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py` -> exit 0
  - радиусы `Services/camera_device/tests`, `router_module/tests`, `multiprocess_prototype/frontend/forms/tests` (medium, `--tb=no -rfE`) -> новых красных нет против снимка лида
  - `ruff check -q` по пяти путям `.py` -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_incomplete_policy.py multiprocess_framework/modules/router_module/tests/test_t47d1_marker_contract.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: маркер на короткий кадр (W2-a2 бросает `IncompleteFrameError`, кадра нет), на `lost_frames` и `trigger_lost` (изделие без снимка) — отдельное решение владельца; показ повреждённого кадра на дисплее (Р-W2-12 б); пакетные узлы `GevSCPSPacketSize`/`GevSCPD` (W2-h, после стенда); железо `camera_0` (порт свитча, руками владельца); README/ADR камеры и поправка ADR-174 — `tech-writer` после слияния.
TRAPS: при `not_inspected` дисплей не получает повреждённый кадр: камера со 100 % неполных (`camera_0` сегодня) даёт тёмный дисплей, и плашка W2-c2 скажет «нет сигнала», хотя поток идёт — это Р-W2-12 (б), не чинить здесь. При `inspect` признак доживает до потребителя, только пока плагины цепочки возвращают тот же dict: плагин, собирающий новый dict, его теряет — не обещать большего. `ctx.health` плагина — один владелец заявки: прямой `set_status("ok")` где-либо ещё в плагине снимет `degraded` доли (W2-a1 тоже пишет здоровье — сверить на базе). `trace_id` маркеру ставит `SourceProducer` (`source_producer.py:231-236`), не плагин.
HANDOFF IN: W2-a2 — `_on_incomplete`, `IncompleteFrameError`.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».

Решение владельца Р-W2-12 (до старта): (а) политика по умолчанию — `not_inspected` (предложение лида) или `inspect`; (б) дисплей при `not_inspected`: без кадра (сейчас в тексте) или кадр на дисплей отдельно от инспекции (новая маршрутизация источника, отдельный план); (в) порог `0.05` и окно 10 с — предложение лида по стенду (5 к/с: 0,2 %; 25 к/с: 80-100 %).
