# app_module — «рыба-шаблон» приложения (generic composition root)

Верхний **композиционный ярус** фреймворка (ярус 2 в модели `app-template-idea.md`).
Собирает под одну крышу код, который сегодня одинаков для любого многопроцессного
приложения: сборка системы, авто-скан плагинов/сервисов, манифест, env-нейтральность.
Цель — второе приложение = **данные + декларации + тонкий bootstrap**:

```python
# examples/minimal_app/run.py
from multiprocess_framework.modules.app_module import run_app
run_app(Path(__file__).parent / "app.yaml")
```

## Инвариант яруса (важно)

`app_module` — **только композиция, ноль механизмов**. Если куску нужна своя логика —
его место в модуле яруса 1 (framework). **Внутри framework никто не импортирует
`app_module`** (он — верх; направление импортов `app_module → остальные`). Enforce:
- `.sentrux/rules.toml` boundary `framework/* → app_module/*`;
- контракт-тест `tests/test_contract.py::test_no_other_framework_module_imports_app_module`.

Внутренние импорты модуля — **относительные** (`.manifest` и т.п.): sentrux не резолвит
relative → boundary ловит только чужие absolute-импорты, не ложно-срабатывая на self.

## Публичный API

Только через `__init__.py` и `interfaces.py`:

| Символ | Роль |
|---|---|
| `run_app(app.yaml | AppSpec)` | точка входа: собрать и запустить (`build_app` — собрать без запуска) |
| `AppManifest` / `load_manifest` | generic-манифест: `name`/`version`/`extras` + пути + `discovery` |
| `ManifestStore` | **единственная точка read/write `app.yaml`** (NEW-1, закрывает гонку backend↔GUI) |
| `discover()` / `DiscoveryResult` / `ServiceManifest` | **единый helper** авто-скана плагинов (`plugin.py`) И сервисов (маркер `service.yaml`) |
| `SystemBuilder` / `AppSpec` | generic-сборка launcher; `AppSpec` — DI-контейнер точек расширения |
| `assemble_proc_dicts` | universal-шов blueprint → proc_dicts (framework-символы) |
| `apply_env_aliases` | `MULTIPROCESS_*` ↔ `INSPECTOR_*` back-compat (де-брендинг) |
| Protocol'ы `BlueprintLoader`/`ProcDictsBuilder`/`StateBootstrap`/`LauncherFactory` | точки расширения (DI вместо наследования) |

## Два режима сборки

- **generic** (`run_app("app.yaml")` — minimal_app/дефолт): granular build-time хуки с
  framework-defaults (`default_blueprint_loader` + `assemble_proc_dicts`), оркестратор —
  базовый `ProcessManagerProcess`. «Рыба» доказывает самодостаточность без прототипа.
- **factory** (`AppSpec.launcher_factory` — прототип): приложение собирает launcher само
  (его сложившийся `SystemBuilder.build()` — источник истины), `run_app` даёт generic-
  контур (env-алиасы, единая загрузка манифеста). Вход прототипа постепенно выражается
  через `run_app`, back-compat полный.

## app.yaml (пример)

```yaml
name: My App
version: 1                    # задел движка миграций
extras: {}                    # app-специфика pass-through (framework не читает)
pipeline: pipeline.yaml        # активный запускаемый pipeline (топология/рецепт)
base: base.yaml                # опц. фундамент (always-on), суммируется с pipeline
discovery:
  plugin_paths: [plugins]      # где искать plugin.py
  service_paths: [services]    # где искать маркер service.yaml
  auto_discover: true
```

## Хуки — два сорта (формализация — Ф5.12)

| Сорт | Где | Форма |
|---|---|---|
| build-time | launcher-процесс, до spawn | обычный callable (`BlueprintLoader`/`ProcDictsBuilder`/`StateBootstrap`) |
| runtime | после spawn | import-path строка + dict (callable не пиклится) — в Ф5.11 не вводится |

Правило против hook-взрыва: хук попадает в `AppSpec`, только если прототип нуждается в
нём сегодня И minimal_app живёт без него (опционален).

## См. также
- Референс-приложение: [`examples/minimal_app/`](../../../../examples/minimal_app/)
- Дизайн: `plans/2026-07-06_constructor-master/app-template-idea.md`
- Решения: [`DECISIONS.md`](DECISIONS.md)
