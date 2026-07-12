# app_module — STATUS

- **Ярус:** 2 (композиция; app-template-idea). Верхняя крыша framework.
- **Статус:** активен с Ф5.11 (2026-07-12). 26-й модуль framework.
- **Зрелость:** skeleton v1 — generic composition root + ManifestStore + discover + env-алиасы.

## Состав

| Файл | Роль |
|---|---|
| `manifest.py` | `AppManifest` (`name`/`version`/`extras` + пути + `discovery`), `load_manifest` |
| `store.py` | `ManifestStore` — единственная точка read/write app.yaml (flock + atomic), NEW-1 |
| `discovery.py` | `discover()` — единый helper плагины (`plugin.py`) + сервисы (маркер `service.yaml`) |
| `env.py` | `apply_env_aliases()` — `MULTIPROCESS_*` ↔ `INSPECTOR_*` back-compat |
| `builder.py` | `SystemBuilder` + `AppSpec` + generic `assemble_proc_dicts` + `default_blueprint_loader` |
| `entry.py` | `run_app` / `build_app` |
| `interfaces.py` | Protocol'ы точек расширения (module-contract) |

## Контракт (module-contract)

- README + interfaces.py (Protocol) + contract-тесты + DECISIONS.md (ADR-APP-001..005) + STATUS.md ✅
- Инвариант яруса: внутри framework 0 импортов app_module — sentrux boundary + `test_contract.py`.

## Тесты

`tests/` — manifest / manifest_store (+ регресс гонки) / discovery / env / builder / contract /
minimal_app smoke (headless boot). Потребители: `examples/minimal_app` (generic-путь),
`multiprocess_prototype` (factory-шов).

## Остаток / следующее

- **Ф5.12:** generic `AppOrchestrator` + формализация двухсортных хуков; `GenericProcessApp`
  → app_module; конвергенция прототипного `BlueprintAssembler` с `assemble_proc_dicts`
  (Inspector-специфика за швом `launcher_factory`, ADR-APP-005).
- **Ф5.13:** `examples/minimal_app` финализация + CI-smoke (BackendHarness); sentrux-boundary
  `examples НЕ импортирует multiprocess_prototype`.
- **GUI-часть «рыбы»:** отдельно (В3/NEW-D2), не в этой волне.
