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
| `ManifestStore` | **единственная сериализованная точка записи** (NEW-1, закрывает гонку backend↔GUI): `update` / `read_raw` — `app.yaml` (умолчание), `set_pipeline` — `<stem>.state.yaml` (активный рецепт) |
| `resolve_active_pipeline` / `ActivePipeline` / `state_path_for` | выбор активного pipeline: валидное состояние перебивает умолчание `app.yaml`; путь файла состояния (ADR-APP-008) |
| `discover()` / `DiscoveryResult` / `ServiceManifest` | **единый helper** авто-скана плагинов (`plugin.py`) И сервисов (маркер `service.yaml`) |
| `SystemBuilder` / `AppSpec` | generic-сборка launcher; `AppSpec` — DI-контейнер точек расширения |
| `assemble_proc_dicts` | universal-шов blueprint → proc_dicts (framework-символы) |
| `default_state_bootstrap` | дефолтный build-time хук: blueprint → state-топология `processes.<имя>.{config,state}` (Ф1 Task 1.0) |
| `GENERIC_ORCHESTRATOR_CLASS_PATH` | import-path generic-оркестратора (дефолт generic-пути) |
| `apply_env_aliases` | `MULTIPROCESS_*` ↔ `INSPECTOR_*` back-compat (де-брендинг) |
| Protocol'ы `BlueprintLoader`/`ProcDictsBuilder`/`StateBootstrap`/`ThrottleRules`/`LauncherFactory` | точки расширения (DI вместо наследования) |

Generic-оркестратор `GenericProcessManagerApp` (`orchestrator.py`) резолвится
child-side по строке (`GENERIC_ORCHESTRATOR_CLASS_PATH`), а не импортируется —
инвариант яруса (внутри framework 0 статических импортов app_module) держится.

## Два режима сборки

- **generic** (`run_app("app.yaml")` — minimal_app/дефолт): granular build-time хуки с
  framework-defaults (`default_blueprint_loader` + `assemble_proc_dicts` +
  `default_state_bootstrap`), оркестратор — `GenericProcessManagerApp`. «Рыба» доказывает
  самодостаточность без прототипа (бутится без единого хука).

  **Дефолтный `state_bootstrap` (Ф1 Task 1.0, ADR-APP-007).** `AppSpec.state_bootstrap`
  не задан → работает `default_state_bootstrap`: blueprint → ветка `processes` вида
  `{<имя>: {"config": {plugins, chain_targets, priority}, "state": {status, pid, fps,
  error}}}`. Так generic-приложение поднимает StateStore, отвечает на `state.get_subtree`
  и видно в `system_overview` — не написав ни строки Python. Явный хук приложения
  **выигрывает целиком** (не мержится с дефолтом). Blueprint без процессов даёт
  `{"processes": {}}`, а не `{}`: непустой dict проходит гейт `_setup_state_store`, и
  приложение без процессов отвечает «поддерево пусто» вместо «обработчика нет».
- **factory** (`AppSpec.launcher_factory` — прототип): приложение собирает launcher само
  (его сложившийся `SystemBuilder.build()` — источник истины), `run_app` даёт generic-
  контур (env-алиасы, единая загрузка манифеста). Вход прототипа постепенно выражается
  через `run_app`, back-compat полный.

## app.yaml (пример)

```yaml
name: My App
version: 1                    # задел движка миграций
extras: {}                    # app-специфика pass-through (framework не читает)
pipeline: pipeline.yaml        # умолчание; активный — в <stem>.state.yaml (топология/рецепт)
base: base.yaml                # опц. фундамент (always-on), суммируется с pipeline
discovery:
  plugin_paths: [plugins]      # где искать plugin.py
  service_paths: [services]    # где искать маркер service.yaml
  auto_discover: true
```

## Активный pipeline: `<stem>.state.yaml` (ADR-APP-008)

`app.yaml` хранит только **умолчание** `pipeline`. Выбор пользователя (CLI `run.py <recipe>`,
выбор рецепта в GUI) пишет `ManifestStore.set_pipeline` в файл состояния рядом с манифестом:
`app.yaml` → `app.state.yaml`, `stand.yaml` → `stand.state.yaml`. Файл в `.gitignore`
(`*.state.yaml`), `app.yaml` при выборе не меняется.

```yaml
# app.state.yaml — создаётся приложением, руками не правится
pipeline: recipes/letter_robot_sim.yaml
```

- **Запись.** Под тем же локом `<manifest>.lock`, что и `update`. Атомарно: temp +
  `os.replace`; при `PermissionError` подмена повторяется (20 × 25 мс). Если содержимое
  уже то же — файл не трогается.
- **Чтение.** `resolve_active_pipeline(manifest_path, default)` лока не берёт и не бросает.
  Состояние принято, если это dict с непустой строкой `pipeline`, указывающей на
  существующий файл (относительный путь — от каталога манифеста). Иначе берётся умолчание
  из `app.yaml`, а `note` называет причину и путь файла состояния.
- **Манифест.** `load_manifest` использует резолвер. `AppManifest.pipeline_origin` —
  `"state"` или `"manifest"`; `AppManifest.pipeline_note` — причина отказа от состояния.
- **Видимость.** Состояние **молча** (только лог) перебивает правку умолчания в `app.yaml`.
  Баннер сборки: `pipeline : <имя> (state)`. Чтобы сменить умолчание, правят `app.yaml` и
  удаляют `<stem>.state.yaml`. Команды «сделать умолчанием» нет.
- **Копия манифеста.** Стенд с `INSPECTOR_MANIFEST=<копия>` получает свой
  `<копия-stem>.state.yaml` рядом с копией.

## Хуки — два сорта (формализованы в Ф5.12, ADR-APP-006)

| Сорт | Где | Форма | Потребление |
|---|---|---|---|
| build-time | launcher-процесс, до spawn | обычный callable (`BlueprintLoader`/`ProcDictsBuilder`/`StateBootstrap`/`ThrottleRules`) | результат (dict) → `orchestrator_config` → пиклится через spawn → оркестратор child-side |
| runtime | после spawn | import-path строка (`orchestrator_class_path`) + dict `orchestrator_config` — callable не пиклится | подкласс `GenericProcessManagerApp` резолвится child-side, переопределяет seam'ы (`_configure_runtime`/`apply_topology`) |

Правило против hook-взрыва: хук попадает в `AppSpec`, только если прототип нуждается в
нём сегодня И minimal_app живёт без него (опционален). Первая пара — доказательство обоих
сортов: **state-bootstrap** (build-time) + **display-reload** (runtime). Пример реализации
runtime-хуков — прототипный `ProcessManagerProcessApp` (тонкая композиция поверх
`GenericProcessManagerApp`).

## См. также
- Референс-приложение: [`examples/minimal_app/`](../../../../examples/minimal_app/)
- Дизайн: `plans/2026-07-06_constructor-master/app-template-idea.md`
- Решения: [`DECISIONS.md`](DECISIONS.md)
