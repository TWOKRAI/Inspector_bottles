# Handoff — truth-holes-closure, Фазы 2 и 3 закрыты (2026-07-23)

**Ветка:** `fix/truth-holes-closure` (14 коммитов, в origin НЕ пушено, дерево чистое)
**План:** [`plans/truth-holes-closure.md`](../../plans/truth-holes-closure.md)
**Предыдущий хендофф:** [`2026-07-22-handoff-truth-holes-phase1.md`](2026-07-22-handoff-truth-holes-phase1.md)

## Что сделано в эту сессию

| Коммит | Что |
|---|---|
| `1dd83ac0` | **Фаза 2 (Task 2.1)** — замена инстанса видима в supervision |
| `dc1d8393` | 6 предсуществующих красных тестов (падали и на `main`) |
| `7e39ce3d` | **Фаза 3** — приёмка ротации живым прогоном |

### Фаза 2 — что именно закрыто

Дыра: при дефолтном reuse-очередей `process.restart` осознанно не бампает incarnation
(fence-семантика), а `restart_count` считает только краш-рестарты → снимок до и после
ручного рестарта был неотличим.

`supervision.status` теперь несёт `pid` (истина ОС), `alive`, `started_at`, `instance_restarts`.
Маркер замены инстанса = **pid + instance_restarts**.

**Live (webcam_sketch, два рестарта `lines`):** pid **24808 → 26476 → 17748**,
`instance_restarts` **0 → 1 → 2**, `incarnation` **0 всё время**, `restart_count` **0**.

### Фаза 3 — приёмка (фикс корня был раньше, `2a48ebe8`)

- живой `webcam_sketch`: `camera_0/system.log.1` = **10 485 676 байт** (ровно лимит);
- файл-виновник `messages.log` (два канала, продовый max_size, реальная сборка `LoggerCore`):
  ротировался **дважды** — `.1`/`.2` по 10.0 МБ, `_rollover_failures` = **0**.

## Что дальше

1. **Фаза 4** — инструментальный трек: 4.1 `introspect.telemetry` (readback gate) → 4.2 verify
   (использует 4.1); 4.3 «кто душит очередь X»; **4.4 `process_restart_verified` разблокирован**
   полями Task 2.1; 4.5 доки.
2. **Фаза 5** — закрывающий live-прогон (Task 5.1), гейт выхода плана.
3. **Фаза 6** — флип дефолтов → soak → **удалить** флаги (6.3 ждёт инвентарь levels-vs-edges
   из `plans/telemetry-pull-on-demand.md`, тот план всё ещё DRAFT и ждёт go-ahead владельца).

## Грабли этой сессии (не повторять)

- **Ревью Fable снова поймало то, что прошло мимо самопроверки** (порядок «ревью → live» оправдался
  второй раз подряд). Находки: (1) имя `manual_restarts` из спеки плана — ложь, авто-рестарт монитора
  идёт той же командой `process.restart` → переименовано в `instance_restarts`; (2) хвосты не
  снимались при удалении процесса → призрак в снимке и наследование счётчика одноимённым.
  **Спека плана может врать — имя поля проверять по коду, а не по плану.**
- **Golden-артефакты дрейфуют молча.** `docs/contracts/CAPABILITIES.yaml` был красным ещё на HEAD:
  в дампе не было канала `ProcessManager_state` из Task 1.2 Фазы 1. Регенерация —
  `python -m backend_ctl.dump_capabilities` (поднимает headless-бэкенд сам).
  Любая правка описания команды или набора очередей → регенерировать.
- **Красный suite был на `main`, а не от ветки.** Прежде чем чинить — проверять переключением веток.
  Причины: gui уехал из `base.yaml` в `frontend/presentation.yaml` (Ф2 frontend-constructor),
  `TopologyGateMiddleware` встал рядом с throttle (индексные проверки ломались на соседе),
  кольца истории уехали в `TelemetryReadModel` (ADR-136).
- **GUI-окно = процесс бэкенда.** Закрытие окна гасит систему (exit 0, выглядит как штатный конец).
  Для live-прогонов окно не трогать, гасить `system.shutdown` → TaskStop.
- **Без флагов Фазы 1 шторм возвращается.** Первый live-прогон дня захлебнулся в never-drop
  `gui system`. Live гонять с `FW_STATE_COALESCE=1 FW_STATE_QUEUE=1` до флипа дефолтов.
- **`| tail` в фоновой команде глушит вывод** — pipe буферизует до выхода процесса; для live-логов
  писать в файл через `>`.

## Запуск live (для повтора)

```bash
FW_STATE_COALESCE=1 FW_STATE_QUEUE=1 BACKEND_CTL=1 \
  .venv/Scripts/python multiprocess_prototype/run.py webcam_sketch > /path/to/live.log 2>&1
```
Строго один инстанс (порт 8765; тестовые харнессы backend_ctl занимают тот же порт —
live и suite параллельно не гонять). Гасить: `system.shutdown` → TaskStop.

## Состояние тестов

- `multiprocess_prototype` — 3249 passed, 14 skipped (было 3243 + 6 failed)
- `process_manager_module` — 501 passed
- `logger_module` — 59 passed
- `backend_ctl` + capabilities — зелёные (12 passed в drift-gate)
- `scripts/validate.py` — чисто
