# app_module — STATUS

- **Ярус:** 2 (композиция; app-template-idea). Верхняя крыша framework.
- **Статус:** активен с Ф5.11 (2026-07-12); Ф5.12 — generic-оркестратор + двухсортные хуки.
- **Зрелость:** skeleton v1 — generic composition root + ManifestStore + discover + env-алиасы
  + `GenericProcessManagerApp` (generic-оркестратор яруса 2).

## Состав

| Файл | Роль |
|---|---|
| `manifest.py` | `AppManifest` (`name`/`version`/`extras` + пути + `discovery`), `load_manifest` |
| `store.py` | `ManifestStore` — единственная точка read/write app.yaml (flock + atomic), NEW-1 |
| `discovery.py` | `discover()` — единый helper плагины (`plugin.py`) + сервисы (маркер `service.yaml`) |
| `env.py` | `apply_env_aliases()` — `MULTIPROCESS_*` ↔ `INSPECTOR_*` back-compat |
| `builder.py` | `SystemBuilder` + `AppSpec` (build-time хуки) + `assemble_proc_dicts` + `GENERIC_ORCHESTRATOR_CLASS_PATH` |
| `orchestrator.py` | `GenericProcessManagerApp` — generic-оркестратор яруса 2 (StateStore/watcher/`_configure_runtime` seam) |
| `entry.py` | `run_app` / `build_app` |
| `interfaces.py` | Protocol'ы точек расширения (module-contract): +`ThrottleRules` |

## Контракт (module-contract)

- README + interfaces.py (Protocol) + contract-тесты + DECISIONS.md (ADR-APP-001..006) + STATUS.md ✅
- Инвариант яруса: внутри framework 0 импортов app_module — sentrux boundary + `test_contract.py`.

## Тесты

`tests/` — manifest / manifest_store (+ регресс гонки) / discovery / env / builder / contract /
orchestrator (хуки+gating) / minimal_app smoke (headless boot generic-оркестратора).
Потребители: `examples/minimal_app` (generic-путь), `multiprocess_prototype` (factory-шов +
`ProcessManagerProcessApp` наследует `GenericProcessManagerApp`).

## Остаток / следующее

- **Ф5.13:** `examples/minimal_app` финализация + CI-smoke (BackendHarness); sentrux-boundary
  `examples НЕ импортирует multiprocess_prototype`.
- **GUI-часть «рыбы»:** отдельно (В3/NEW-D2), не в этой волне.

## Задача 3.3 (2026-08-11) — `assemble_proc_dicts` не материализует каталог логов (ADR-138)

Было `log_dir: str = "logs"`, и эта строка попадала в конфиг КАЖДОГО процесса. Следствие:
`_resolve_log_dir` смотрит на `MULTIPROCESS_LOG_DIR`/`INSPECTOR_LOG_DIR` только когда каталог
НЕ задан — то есть наш дефолт бил волю вызывающего, и увести логи из `cwd` было **нечем**:
поля `log_dir` нет ни у `build_app`, ни у `app.yaml`, ни у `AppSpec`. `examples/minimal_app`
писал **111 354 байта** за прогон своего модуля в `<репозиторий>/logs/`, хотя тест выставлял
env и утверждал в докстринге «свой лог-каталог».

Стало `log_dir: str | None = None`; при `None` каталог в конфиг не пишется, и решает тот, кто
ниже (env → temp). Явное значение работает как прежде. Тот же класс модуль уже знал про себя —
докстринг рядом объясняет, почему `expand_observability` делается внутри: «разложенный снаружи
L1 материализовал бы дефолты и стал бы неперебиваемым».

**Названное ограничение:** ветка `if not cfg.log_dir` выглядит как «уважаем каталог, заданный
процессу рецептом», но у `ProcessConfig` топологии поля `log_dir` нет — ложной она на этой
дороге не бывает. Тревожная растяжка стоит в `tests/test_log_dir_not_materialized.py`.
