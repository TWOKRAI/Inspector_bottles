# Фаза 5 — закрывающий прогон всех 49 инструментов backend_ctl (2026-07-23)

**Рецепт:** `webcam_sketch`, 8 процессов, флаги `QT_MCP_PROBE=1 FW_STATE_COALESCE=1 FW_STATE_QUEUE=1 BACKEND_CTL=1` — **с живым GUI** (в отличие от headless-прогона 2026-07-22, где вся плоскость `ui_*` была NA).
**План:** [`plans/truth-holes-closure.md`](../../plans/truth-holes-closure.md), Task 5.1 — гейт выхода плана.
**Сырые вердикты:** [`evidence_2026-07-23_phase5/`](evidence_2026-07-23_phase5/) (71 строка JSONL, два захода).

**Путь вызова — тот же, что у MCP-сервера:** `dispatch_tool(DriverSession(...), tool, args)`, а не
driver напрямую. Иначе проверялся бы драйвер, а не инструмент. Свежий процесс: запущенный
MCP-сервер держит код на момент старта (ограничение Task 4.5, подтверждено в Фазе 4).

## Итог

| | |
|---|---|
| Инструментов в реестре | **49** |
| Вызвано | **49** (не вызванных нет) |
| Вердикт **OK** | **49** |
| **SUSPECT** (сигнал есть, доверия нет) | **0** |
| **NA** (проверить нечем в рецепте) | **0** |

**Вечное «`ui_*` NA» закрыто окончательно:** `ui_tap` → `success` с атрибуцией
(`sources=[gesture, command]`), `ui_tap_ping` → `events_sent=9, send_errors=0`,
`ui_untap` → снятие подтверждено. `capabilities` отдаёт **8 карточек, включая `gui`** —
после Фазы 1 карточка gui ожила (раньше gui был задушен state-штормом и не отвечал).

## Ключевые доказательства

| Инструмент | Живое свидетельство |
|---|---|
| `capabilities` | 8 карточек, `gui` присутствует |
| `get_status(gui)` | pid отвечает, воркеры видны |
| `introspect_telemetry` | Ф4.1: `gated_metrics` полон, gate читается |
| `introspect_router_stats` | `queue_senders` по 9 очередям, `queue_never_drop_loss_total` доступен |
| `introspect_memory` | rss=137 МБ |
| `register_snapshot` | **5 процессов с регистрами** (`devices`, `lines`, `points`, `pult`, `seg`) |
| `set_register_verified` | `lines.edge_detection.invert` → `verified=True, expected=actual=True` |
| `register_confirm` | `commit_id=lines:edge_detection.invert#1` → `confirmed=True` |
| `register_restore` | `written=1, skipped=127, verified=128, mismatches=[]` |
| `telemetry_set(verify)` | пара `off/on` → `verified_effect=True` обе, `semantics=delivered` |
| `config_reload` | `DEBUG→DEBUG`, обратно `INFO→INFO` (пара) |
| `telemetry_snapshot` | count=**506** метрик, `ingested_total`=3070, `ingest_active=True` |
| `telemetry_history` | **100 точек** по `processes.camera_0.state.fps` |
| `await_condition` | пара: выполнимое (`fps > 1.0`) → `success=True`; невыполнимое (`> 99999`) → `timed_out=True, events_seen=342, last_seen={fps: 15.0}` — таймаут возвращает ДИАГНОЗ, не пустоту |
| `record_*` | запись → `events_written=70` → `record_load` (replay) → `record_unload` (live) → `record_dump` |
| `process_restart_verified` | Ф4.4: `lines` pid **11492 → 31280**, `instance_restarts` 0→1, `alive=True`, 6.59 с |
| `session_log` | 8–10 записей аудита write/escalated |

## Чему научил сам прогон: пять ложных SUSPECT'ов дал harness, а не инструменты

Первый заход дал 7 SUSPECT. Ни один не оказался дефектом инструмента — **все пять причин
были в проверяющем скрипте**, и это стоит записать, потому что каждая уже встречалась:

1. **Чтение не того уровня конверта.** `dispatch_tool` отдаёт router-конверт
   (`{type: response, result: {...}}`); скрипт читал верхний уровень → сплошные `null` →
   ложные SUSPECT у семи introspect-ручек. Тот же класс ошибки, что в verify-скрипте
   2026-07-17 («all-null был багом моего скрипта»).
2. **Усечённый ответ ≠ пустой ответ.** `telemetry_snapshot` вернул 102 КБ → сработал
   `RESPONSE_BYTE_CAP`, и ответ пришёл как карта формы `{_truncated, _hint, keys: {...}}`.
   Поле `count` никуда не делось — оно внутри `keys`. Читатель, ждущий `count` на верхнем
   уровне, видит «нет данных» там, где данных 506 метрик.
3. **Самодельная фабрика драйвера без `connect()`.** Прод-сессия (`_default_driver_factory`)
   делает `connect()` + readiness-пробу; моя лямбда — нет. Итог: `not connected` у пяти
   инструментов подряд и деградация `capabilities` до одного процесса.
4. **Значения read-model — dict `{value, process, worker}`, не голое число.** Фильтр
   `isinstance(v, (int, float))` не нашёл ни одной живой метрики при семи живых fps.
5. **Отписка без подписки в этой сессии.** `log_untail` честно вернул `success=False` —
   `log_tail` в той сессии не вызывался. Инструмент прав, скрипт нет.

Инструмент, который должен показывать правду, сам стал жертвой того же класса ошибок,
против которого затеян план: **сигнал был, а читатель брал его не оттуда**. Отсюда
follow-up в докках (см. ниже) — не для кода, а для читателя ответов.

## Гейт выхода плана

- [x] **gui отвечает live** — `get_status(gui)` с pid, карточка `gui` в `capabilities`
- [x] **`ui_*` доказаны** — tap / ping (`events_sent=9, errors=0`) / untap на живом GUI
- [x] **ротация живая** — Фаза 3 (`camera_0/system.log.1` = 10 485 676 байт; `messages.log` ×2)
- [x] **supervision показывает замену инстанса** — pid 11492 → 31280, `instance_restarts` 0→1
- [x] **0 инструментов с UNPROVEN-эффектом** — 49 OK, 0 SUSPECT, 0 NA

Функциональная часть плана закрыта. Остаётся **Фаза 6** (снятие лесов: флип дефолтов →
soak → удаление флагов) — план не считается закрытым, пока живы флаги Фазы 1.
