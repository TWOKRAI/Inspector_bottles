# P0 блокер кадров при hot-swap: однофазная сборка ломает межпроцессную доставку

**Дата:** 2026-06-06
**Ветка:** `fix/recipe-v3-engine-decouple`
**Slug:** `frames-blocker-hotswap-wiring`
**Метод:** live-репро (qt-mcp + DIAG-инструментирование + пер-процессные логи). Корень доказан на работающем приложении, не статикой.

---

## Симптом

- **Fresh boot любого рецепта** (region_pipeline / color_inspect): кадры идут, FPS 22, картинка живая
  (color_inspect рисует зелёные контуры). Всё исправно.
- **Hot-swap рецепта** (Recipes «Загрузить», в ОБЕ стороны): «Активен: X» меняется, но картинка
  **замерзает на последнем кадре прошлого рецепта**, FPS 0.

## Что ИСКЛЮЧЕНО (живыми тестами — важно, чтобы не чинить не то)

1. **НЕ SHM `output_frames` lazy-alloc** — на boot всё работает; ошибок «not found» в свопе нет.
2. **НЕ утечка камеры / device contention** — DIAG показал: старый camera_0 при стопе делает
   `shutdown START → DONE` за **0.07–0.4с** (камера освобождается ШТАТНО), новый открывает её через ~7с
   (контеншена нет).
3. **НЕ producer-цикл** — DIAG в `SourceProducer.run_loop`: новый camera_0 `run_loop ENTER stop=False
   pause=False targets=['detector']` → `produce() РАБОТАЕТ — читаю кадр` → iter#1. **Камера производит кадры.**

## Root cause (ДОКАЗАН)

**Кадры камеры не доходят до consumer'а (`detector`) между процессами после hot-swap.**
- camera_0 (новый) производит и шлёт в `detector`;
- `detector` поднялся (`data pipeline started, 2 processing plugins`), но **получает НОЛЬ сообщений**
  (нет message-активности после свопа) → painter без активности → GUI перестаёт принимать кадры → FPS 0.

**Почему — конкретно в коде:**

| Путь | Как стартует | Очереди |
|------|--------------|---------|
| **boot** `_create_processes_from_config` ([pm_process.py:996](../multiprocess_framework/modules/process_manager_module/process/process_manager_process.py#L996)) | **ДВУХФАЗНО**: 1) `register_process` (очереди) ВСЕХ; 2) `create+start` ВСЕХ | каждый процесс при спавне видит очереди всех остальных |
| **hot-swap** `replace_blueprint` step 7 ([pm_process.py:798-825](../multiprocess_framework/modules/process_manager_module/process/process_manager_process.py#L798)) | **ОДНОФАЗНО**: `register_process`+`create_and_register`+`start` по одному процессу за раз | процесс, стартующий раньше, получает spawn-bundle (snapshot shared_resources) **до** регистрации очередей более поздних процессов |

`color_inspect` начинается с `camera_0` (порядок processes в рецепте) → camera_0 спавнится **первым**, его
spawn-bundle формируется **до** регистрации очередей `detector` → новый camera_0 шлёт в `detector`, которого
нет в его локальном `shared_resources` → кадры уходят в «пустоту». На Windows-spawn каждый процесс держит
СВОЮ копию shared_resources из bundle (момент спавна), поэтому поздняя регистрация detector не видна камере.

> **Связь с планом `recipe-orchestrator-unify`:** это ровно «ad-hoc hot-swap не повторяет корректную сборку
> boot». «boot == switch» (двухфазный чистый рестарт) чинит этот класс багов структурно.

## Фикс (surgical, mirror boot)

**Сделать `replace_blueprint` step 7 двухфазным — как `_create_processes_from_config`:**
1. Фаза 1: для всех новых non-protected proc_dict → `shared_resources.register_process(name, proc_dict)`
   (создать ВСЕ очереди до спавна).
2. Фаза 2: для всех → `create_and_register` + `start` + `apply_priority`.
- Сохранить rollback-семантику (snapshot, restore при ошибке) и `_process_configs`.
- (Опц., после) переиспользовать общий хелпер сборки/спавна между boot и switch — шаг к `recipe-orchestrator-unify`.

## Acceptance (live)
- [ ] После switch region_pipeline ↔ color_inspect: detector получает кадры, painter рисует контуры,
      GUI обновляется, FPS > 0 (qt-mcp скриншот в обе стороны).
- [ ] Нет регрессий boot (оба рецепта стартуют с кадрами).
- [ ] Тесты `test_replace_blueprint` зелёные; sentrux health не ниже baseline.
- [ ] Снять DIAG-инструментирование (source_producer.run_loop, CapturePlugin.produce/shutdown) после фикса.

## Вне scope
- Унификация оркестрации (`recipe-orchestrator-unify.md`) — отдельно; этот фикс — её частный случай/предвестник.
- Camera release / SHM lazy-alloc — подтверждённо НЕ причина; не трогаем.

## Инструментирование (временное, снять после)
- `Plugins/sources/capture/plugin.py`: DIAG в `produce()` (guard/работает), `shutdown()` (START/DONE), пустые read.
- `multiprocess_framework/.../generic/source_producer.py`: DIAG в `run_loop` (ENTER/iter/EXIT).
