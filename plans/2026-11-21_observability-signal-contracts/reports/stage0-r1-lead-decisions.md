# Стадия 0, раунд 1 — решения лида по вердиктам 0.1, 0.2, 0.3

Источник: `0.1.review-r1.md`, `0.2.review-r1.md`, `0.3.review-r1.md` (рядом). Все три — CHANGES REQUESTED. Решения лида полосы Н,
2026-11-21; решения, меняющие литералы плана, идут поправками в `amendments.md` и вынесены на вето владельца/координатора.
Принцип: тексты Task описывают всё, что нужно слепому tester и исполнителю; ничего не выводят из кода.

## Задача 0.1
- **M1 → вариант A.** Ответный `failed` и `refused` звена `channel` считаются в `channel_refused_records` (ADR-CRM-011 сохраняется:
  `channel_write_errors` = звено БРОСИЛО исключение). Таблица `LOSS_KEY_BY_HOP`: `channel` refused и failed → `channel_refused_records`;
  `tap` refused → `tap_refused_records`, failed → `tap_write_errors`; `bridge` оба → `lost_responses`.
  Цель 2 плана → `channel_refused_records` 4 (а не `channel_write_errors`); REDS и DESIGN 0.4 приводятся к этому. Поправка № 2 в amendments.
  Метка «вето»: вариант B (пересвязка `_write_record_to_channels`) отвергнут как ломающий закреплённые тесты вне FILES.
- **M2:** принять. Расширение `refused` — осознанное, строка в ADR-CRM-019; принадлежность статуса — кортежем; `test_channel_accepted_parity` (13 литералов).
- **M3:** подраздел «Форма пробы» (таблица из ревью) в Task и в README «Исход звена». Для (г) контракт читает ТОЛЬКО счётчик `lost_responses`
  (носитель — `get_stats()`); `on_inbound` исход не возвращает, 0.5 это не меняет. Для (в) именованный ключ — `channel_refused_records`
  (сверить с REDS 0.6 и привести к одному ключу).
- **M4:** INTERFACE даёт ПОЛНЫЕ тела `outcome_of` и `count_outcome`; unit-тесты пишет teamlead до INTERFACE; RED tester'а: `4 failed, 4 passed`, красные — `AssertionError`.
- **M5:** unit-тесты и таблица инъекций из ревью; инъекцию (2) переписать.
- **M6:** фразу «звено не вправе улучшить исход нижнего» УДАЛИТЬ из 0.1 (ponytail: нет вызывающего у `worst`); свойство — приёмка 0.5/0.6 (экземпляры).
- **M7:** ключ `tap_refused_records` в `LOSS_COUNTER_KEYS`/`PLANE_COUNTER_KEYS` вводит Task 0.5 (+ `process_module/managers/observability_reload.py`
  в FILES 0.5, + проверить `backend_ctl/protocol.py:325`, `backend_ctl/tests/test_overview.py:587`); 0.1 создаёт `count_outcome` на обычном dict.
- **M8:** глобальный ADR «три контракта» переносится в Task 0.3 (`multiprocess_framework/DECISIONS.md`); в 0.1 — `ADR-CRM-019` в
  `channel_routing_module/DECISIONS.md` + шаги `python -m scripts.sync`, `python scripts/validate.py`; `design.md` §9 поправить.
- **M9:** текст `count_outcome` из ревью (возвращает None, мутирует, лок у вызывающего, `ValueError` без значения).
- **M10–M14:** внести (M10 — в Task 0.5: путь `_emit_to_taps` и `send` против `send_async`, сверить по коду). `Gate:` — не вносить (общий пункт плана, не замечание 0.1).
- Level остаётся Senior. Пилот не нужен (ответ координатора).

## Задача 0.2
- **№1 → вариант A:** `[tree]` проверяет «конверт переживает `handle_state_merge` → `get_subtree` и классифицируется», зелёный с GREEN 0.2;
  убрать `[tree]` из REDS 0.2 и из REDS 0.9; что писатель кладёт метку — тесты 0.9 и 0.13. Красные после GREEN: `[read_model]` ×2 (до 0.10), `[telemetry_snapshot]` ×2 (до 0.10b).
- **№2:** таблица «адаптеры читателей» (черновик из ревью). Решения: `TelemetryReadModel(clock=…)`, `rm.ingest(P, sub)`, `rm.read(path, key, alive_incarnation=None)` — имя и форму фиксирует 0.10 (согласовать);
  `BackendDriver(clock=…)` — ctor-параметр, вводит 0.10b (в 0.2 красный по `TypeError` / отсутствию ключа `class`); форма `metrics[path] = {"value", "class", "age_s", …}`;
  листья `_fresh.*` фильтруются из `telemetry_snapshot.metrics` (0.10b).
- **№3:** `classify` и `read_value` всюду определены, исключений не бросают; негодная метка (не dict, нет любого из четырёх ключей, nan/inf/bool, `tick_sec <= 0`) → `no_data`;
  «задан» = `is not None`; отрицательный возраст → `fresh`, `age_s` отрицательный как есть (без обрезки); `age_s` у `no_data` = `None`; у stale/writer_gone = `now - src_ts`.
- **№4:** литералы из ревью (граница `110.0` → `fresh`; `age_s` через `approx`; ключ `None` → `no_data`; `stamp(...) ==` литерал с четырьмя ключами). Поправить `tasks/0.10.md:29` (`approx`).
- **№5:** инъекции (1)–(7) из ревью, предсказания по моментам (после GREEN 0.2; после 0.10/0.10b).
- **№6:** REDS в два блока (красные до GREEN / красные после GREEN); причины читателей: `AttributeError: no attribute 'read'`, нет ключа `class`; контракт не должен краснеть по `ImportError` — заглушка INTERFACE в TRAPS.
- **№7:** `freshness.py` — только stdlib; `backend_ctl` импортирует из `state_store_module.core.freshness`, зеркала нет; `sentrux check .` → 0.
- **№8–12:** внести. README модуля переходит из 0.10 в 0.2; FILES становится 7 — вписать обоснование («два файла tester'а — одна поставка приёмки») и пометить для раунда 2 ревью; `tasks/0.10.md` — убрать шаг README.
- Level остаётся Senior.

## Задача 0.3
- **№1:** таблица «инструмент → команда на проводе → ключ успеха → rejected → accepted» (из ревью). `judge` — только для `set_register_verified` и по полю `register_restore`;
  `process_restart_verified` и `config_reload_verified` читают собственные ключи.
- **№2:** `register_restore`: `rejected` строится с `pre != target` (запись уходит); равное состояние — отдельный контракт-тест
  `test_restore_equal_state_reports_vacuous` (`written 0`, `success True`, `vacuous` = число полей; красный: нет ключа). Тест входит в контракт.
- **№3:** BCTL-ADR-008 уважаем: `success` — про применение, не вердикт; `judge` к `config_reload_verified` не применять; контракт: при отказе хоста `success False` и `verdict != "confirmed"`;
  ложную `verdict_reason` («процесс не вынес суждения…» при переданной inline-секции) чинит 0.11 — в FILES 0.11 добавить `backend_ctl/driver.py`.
  Приписка к форме: в 0.3 `success = verdict in {confirmed, vacuous}` только внутри `judge`.
- **№4:** `telemetry_set(verify=True)` — ПЯТЫЙ инструмент контракта (`driver.py:1844-1916`); экземпляр чинит 0.11 (FILES 0.11 + `driver.py`). Контракт: 5 × 2 + 1 (restore vacuous) = 11 тестов в `test_contract_verified.py`;
  счёт `backend_ctl` в цели 1 плана: 2 (0.2) + 11 = **13 passed**. Поправка № 3 в amendments (цель 1). OUT OF SCOPE: `set_register(confirm_within)` (2.6), `register_confirm`, `run_*` — с причинами.
- **№5:** определение «отказ ack» из ревью (таймаут, None, не-dict, dict без success/status — не отказ).
- **№6:** `judge(pre, ack, post, target, *, unreadable=(), eq=operator.eq)`; 0.11 передаёт `RegisterOps._values_match`; `test_coerced_string_target_is_confirmed`.
- **№7:** порядок правил из ревью (1 отказ ack → failed; 2 unreadable → unverifiable; 3 `not eq(post,target)` → failed; 4 `eq(pre,target)` → vacuous; 5 confirmed);
  `vacuous = ("pre" not in unreadable) and eq(pre, target)` при любом вердикте.
- **№8:** инъекции (1)–(6) из ревью; строку ACCEPTANCE про красные заменить командой и списком красных.
- **№9:** TRAPS — образцы подмены драйвера; assert попытки записи до «не success»; assert наличия ключа успеха.
- **№10–12:** внести (счёт 13; `scripts.sync` не нужен для BCTL; DbC в `verdict.py`). Глобальный ADR «три контракта» (из 0.1) принимает 0.3: `multiprocess_framework/DECISIONS.md` + `python -m scripts.sync`, `validate.py` (FILES 0.3 → 6 максимум: если больше — убрать README и сослаться на ADR, пометить для раунда 2).
- Level остаётся Middle+.

## Поправки плана (amendments.md, лид)
№ 2: цель 2 → `channel_refused_records` 4. № 3: цель 1 → 12 passed (фреймворк) и 13 passed (backend_ctl). № 4: ключ `tap_refused_records` и `observability_reload.py` — в 0.5. № 5: `driver.py` в FILES 0.11 (config_reload reason, telemetry_set verify). № 6: глобальный ADR «три контракта» — из 0.1 в 0.3.
