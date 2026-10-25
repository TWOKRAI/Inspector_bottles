# План: последний активный рецепт — локальное состояние вне git (C-21(б))

**Дефект:** C-21, `plans/queue/defects.md`. **Полоса:** Д. **Ветка:** `fix/app-active-recipe-state`.
**Решение владельца (2026-10-21, вариант (б)):** «последний активный рецепт» — состояние пользователя
в локальном файле вне git; `app.yaml` хранит только умолчание. Правка во framework (`app_module`)
и в прототипе, для любого приложения.

**Статус (2026-10-25):** Task C21.1 DONE на ветке; ревью задачи APPROVED (Sonnet, 2 раунда), ревью ветки
APPROVED (Opus); стенд и A18 зелёные. Отчёт — `docs/reports/2026-10-25_defect_C-21.md`. Ждёт merge в main.

## Симптом (воспроизведён дважды)

1. 2026-10-21, стенд `letter_robot_sim` (полоса Д): `run.py <recipe>` → `persist_pipeline_choice` →
   `app.yaml: pipeline` переписан, рабочее дерево грязное.
2. 2026-10-25, main (координатор): владелец выбрал рецепт в GUI → `_persist_active_recipe` →
   `multiprocess_prototype/app.yaml: pipeline: recipes/qr_reader_sdk_dual_demo.yaml` →
   `recipes/letter_robot_sim.yaml`. Tracked-файл изменён действием пользователя в GUI.

## Карта (чтение 2026-10-25, main `2fe52b93e`; подтверждена стадией 0)

Писатели `pipeline` — все через `ManifestStore.set_pipeline` (`app_module/store.py:121`):
- backend CLI — `multiprocess_prototype/backend/launch.py:427` `persist_pipeline_choice` (зовёт `main.py:140–152`);
- GUI — `multiprocess_prototype/frontend/app.py:842–854` `_persist_active_recipe`;
- хаб рецептов — `multiprocess_prototype/orchestrator.py:146` `persist_active` (для `RecipeService`).
Прямых `update({"pipeline": …})` вне тестов нет.

Читатели `pipeline` — ДВА парсера `app.yaml`:
- framework `app_module/manifest.py:110` `load_manifest` (через `ManifestStore.load`: `builder.py:312`,
  `orchestrator.py:368`, прототип `orchestrator.py:118/140/150` `read_active`);
- прототип `multiprocess_prototype/backend/config/manifest.py:116` `load_manifest` (backend
  `main.py:109` в `_prototype_launcher_factory`, GUI `frontend/app.py:158` → `_manifest.pipeline` в `:262` и restore `:546`).
Сырое чтение одно: `backend_ctl/probes/probe_observability_consumer_acceptance.py:129` (apps/line_sim, без писателя — не трогаем).
Обе `AppManifest` — голый `BaseModel`, через процессы не пикелятся: новые поля с дефолтами безопасны.

### Task C21.1 — активный pipeline в sidecar-состоянии, `app.yaml` только умолчание
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** выбор рецепта (CLI, GUI, хаб) пишет `<stem>.state.yaml` рядом с манифестом, а не `app.yaml`;
оба парсера манифеста берут `pipeline` из состояния, если оно валидно, иначе умолчание из `app.yaml`.

#### C21.1 — DESIGN: framework
1. `app_module/store.py`:
   - `state_path_for(manifest_path) -> Path`: `<каталог манифеста>/<stem>.state.yaml`
     (`app.yaml` → `app.state.yaml`, `stand.yaml` → `stand.state.yaml`). Путь манифеста приводится
     через `.resolve()`: относительный и абсолютный путь дают один файл.
   - `ManifestStore.set_pipeline(value)` пишет `{pipeline: value}` в файл состояния под тем же
     EX-локом `<manifest>.lock`, атомарно (temp + `os.replace`). Файл пишется всегда, когда его
     содержимое отличается от `{pipeline: value}` (с `app.yaml` не сравнивается); при совпадении — не трогается.
     `os.replace` при `PermissionError` повторяется: 20 попыток по 25 мс, затем исключение наружу
     (читатели без лока держат файл открытым — зонд стадии 0: `[WinError 5]` у писателя).
     `app.yaml` не открывается на запись: байты и mtime не меняются. Возврат — записанная строка.
   - `update()` и `read_raw()` остаются про `app.yaml`, то есть про умолчание. Докстринг: `update({"pipeline": X})`
     меняет умолчание; активным остаётся валидное состояние.
   - `resolve_active_pipeline(manifest_path, default_value) -> ActivePipeline` — frozen dataclass
     `path: Path`, `origin: Literal["manifest", "state"]`, `note: str | None`. **Лока не берёт**:
     зовётся и под локом (`ManifestStore.load`, `_PROCESS_LOCK` не реентерабельный → deadlock), и без него.
     Чтение одним `read_text`; при `OSError` — 3 повтора по 25 мс, затем умолчание + `note`. Правило:
     - файла состояния нет → умолчание, `note=None`;
     - файл читается, это dict, `pipeline` — строка, непустая после `.strip()`, путь — файл (`is_file()`,
       не `exists()`) → `origin="state"`. Относительный путь — от каталога манифеста, результат `.resolve()`;
     - иначе (битый YAML, пустой файл, не dict, `pipeline` нет / не строка / `null` / пробелы, каталог,
       несуществующий файл, `ValueError` от пути с `\0`) → умолчание, `note` = причина с путём файла
       состояния. Резолв и проверка в `except (OSError, ValueError)`. Наружу ничего не идёт; файл
       состояния не удаляется и не правится резолвером (`set_pipeline` битое состояние перезаписывает).
2. `app_module/manifest.py`: `AppManifest` получает `pipeline_origin: Literal["manifest","state"] = "manifest"`
   и `pipeline_note: str | None = None`; `load_manifest` берёт `pipeline` через `resolve_active_pipeline`.
   Импорт `store` в `manifest.py` — верхнего уровня (`store.py` импортирует `manifest` лениво, `:91`; цикла нет).
   `_resolve` в `store` не импортировать — три строки локально. Нет ключа `pipeline` в `app.yaml` — по-прежнему `KeyError`.
3. `app_module/builder.py:481` баннер: `pipeline : <name>` + ` (state)` при `origin == "state"`.

#### C21.1 — DESIGN: прототип и документы
4. `backend/config/manifest.py::load_manifest` зовёт ТОТ ЖЕ `resolve_active_pipeline`; импорт — внутри тела
   функции (пакет `app_module` тянет builder, ~1,0 с; модуль сейчас лёгкий). Те же два поля в его `AppManifest`.
5. `main.py`: лог в `main()` — «активный рецепт записан в состояние: <путь state>», логика не меняется.
   `_prototype_launcher_factory` (`main.py:107–110`) после `load_manifest` печатает в stderr: `pipeline_note`,
   если не пуст; при `origin == "state"` — `[run] pipeline: <путь> (источник: состояние <state-путь>)`.
   GUI restore (`frontend/app.py:545–558`) пишет `pipeline_note` через `process._log_warning`.
6. `backend/launch.py:403` `_resolve_pipeline`: голое имя CLI-override резолвится от `app.recipes`
   (`app.recipes / f"{override}.yaml"`), а не от `app.pipeline.parent`. Ветки `recipes is None` нет:
   в прототипном `AppManifest` `recipes: Path` обязателен (`backend/config/manifest.py:81`). Причина: состояние с явным путём вне `recipes/` (`run.py backend/topology/x.yaml`) иначе ломало бы
   голые имена в ~10 тестовых модулях (`from_manifest(app, "phone_sketch")`), а файл не виден в `git status`.
7. `.gitignore`: строка `*.state.yaml` (сейчас под git таких файлов нет; `*.yaml.lock`, `*.yaml.tmp.*` уже есть).
8. ADR-APP-008 в `app_module/DECISIONS.md`: уточняет ADR-APP-003 (писатель тот же, цель записи —
   состояние; `read_raw`/`update` — умолчание; состояние перебивает умолчание, видно по логу). Затем
   `python -m scripts.sync`. README `app_module`: раздел про `<stem>.state.yaml`.
9. `multiprocess_prototype/backend/tests/test_presentation_overlay_on_hot_swap.py::test_overlay_reaches_the_builder_through_the_real_front_entry_switch`
   (`:143–144`): оба вызова `from_manifest` получают явный `"phone_sketch"`
   (`from_manifest(app, "phone_sketch", include_presentation=…)`). Это единственный тест без override на
   реальном манифесте (стадия 0, `git grep`); остальные 8 модулей с голым именем после п.6 от состояния
   не зависят. Autouse-фикстуры нет: она прятала бы именно ту зависимость, которую надо видеть.

**Не меняется:** сигнатуры `persist_pipeline_choice`, `_manifest_pipeline_value`, `set_pipeline`,
`RecipeService`; валидация «рецепт не найден → `FileNotFoundError`, ничего не записано» (Ф6.х.6);
лок и атомарность (ADR-APP-003); `effective_override = None` после успешной записи в `main.py`.
**`multiprocess_prototype/app.yaml` в задаче не трогать**: в main у владельца незакоммиченная правка
этого файла, merge упрётся в неё. Комментарий в файле (строки 41–43) — после решения владельца.

#### C21.1 — Files
1. `multiprocess_framework/modules/app_module/store.py`, `manifest.py`, `builder.py` (баннер),
   `__init__.py` (экспорт `resolve_active_pipeline`, `ActivePipeline`, `state_path_for`)
2. `multiprocess_framework/modules/app_module/orchestrator.py:297,356` — докстринги «app.yaml: pipeline»
3. `multiprocess_framework/modules/recipe/yaml_io.py:10` — докстринг
4. `multiprocess_prototype/backend/config/manifest.py`
5. `multiprocess_prototype/main.py` (логика п.5; докстринг `:116–119`)
6. `multiprocess_prototype/backend/launch.py` — `_resolve_pipeline` (п.6), докстринг `persist_pipeline_choice`
7. `multiprocess_prototype/frontend/app.py` — лог в restore, докстринги `:540–543`, `_persist_active_recipe`;
   `frontend/runtime_deps.py:110`, `multiprocess_prototype/orchestrator.py:130`,
   `multiprocess_prototype/backend/orchestrator_hooks.py:107` — докстринги
8. `scripts/run_sim_all.ps1:24–25` — комментарий «вернуть: `git checkout -- app.yaml`» больше не нужен
9. `.gitignore`; `app_module/DECISIONS.md`, `app_module/README.md`
10. Тесты автора:
    - `app_module/tests/test_manifest_store.py`: `test_set_pipeline_noop_when_unchanged` пуст → заменить на проверку A7;
    - `backend/topology/tests/test_persist_pipeline_choice.py`: красный `test_persist_writes_bare_name_as_recipe_path`;
      пустые `test_persist_preserves_comments`, `test_persist_is_idempotent_no_rewrite` → «`app.yaml` байт в байт + состояние»;
    - `backend_ctl/tests/test_recipe_service_restart_live.py::test_activate_survives_backend_restart` (`:79`) — читать
      `manifest.with_name("app.state.yaml")`, утверждать, что `pipeline` временного `app.yaml` не изменился;
    - `TestBothLoadersAgree` — сверять ещё `pipeline`, `pipeline_origin`, `pipeline_note`;
    - `backend/tests/test_presentation_overlay_on_hot_swap.py` — DESIGN 9.

#### C21.1 — Acceptance criteria (A1–A9)
Слепой тестер пишет их до кода; все с `tmp_path`, без реального `app.yaml`. Манифест для прототипного
парсера обязан нести `system:` и `recipes:` (без них `KeyError`). Рецепт состояния создаётся файлом, иначе состояние невалидно.
- [x] A1. `app.yaml: pipeline: recipes/a.yaml`, `set_pipeline("recipes/b.yaml")` → байты `app.yaml` равны исходным;
      `yaml.safe_load(app.state.yaml) == {"pipeline": "recipes/b.yaml"}`.
      A1b. Нет состояния, умолчание `recipes/a.yaml`, `set_pipeline("recipes/a.yaml")` → `app.state.yaml` создан
      с `{"pipeline": "recipes/a.yaml"}`.
- [x] A2. После A1 (с созданным `recipes/b.yaml`) framework `load_manifest(app.yaml).pipeline == (tmp_path/"recipes"/"b.yaml").resolve()`,
      `pipeline_origin == "state"`.
      A2b. После A1 `ManifestStore(app.yaml).load()` вызывается в daemon-потоке с `join(10)` → поток завершён,
      `.pipeline == (tmp_path/"recipes"/"b.yaml").resolve()`, `.pipeline_origin == "state"`.
- [x] A3. Оба парсера (framework и `multiprocess_prototype.backend.config.manifest.load_manifest`) в одном тесте
      дают одинаковые `pipeline`, `pipeline_origin`, `pipeline_note` — для валидного состояния, для его отсутствия и для битого.
- [x] A4. Нет файла состояния → `pipeline` из `app.yaml`, `pipeline_origin == "manifest"`, `pipeline_note is None`.
- [x] A5. Состояние указывает на несуществующий рецепт → умолчание, `origin == "manifest"`, `note` содержит подстроку
      `app.state.yaml`; исключения нет; байты и `st_mtime_ns` файла состояния не изменились.
- [x] A6. Каждый случай — умолчание + непустой `note`, без исключения: битый YAML; пустой файл (0 байт); список;
      `pipeline: 5`; `pipeline: ""`; `pipeline: "   "`; `pipeline: null`; `pipeline: "a\0b.yaml"` (в YAML-тексте —
      экранированная последовательность `\0` в двойных кавычках, не NUL-байт); `pipeline: recipes/dir`, где каталог `recipes/dir` создан.
- [x] A7. `set_pipeline("recipes/b.yaml")`; `os.utime(state, ns=(t0, t0))` с t0 в прошлом; повторный `set_pipeline`
      тем же значением → `st_mtime_ns == t0`.
- [x] A8. `persist_pipeline_choice(manifest, "b")` → `app.yaml` байт в байт прежний, состояние `{"pipeline": "recipes/b.yaml"}`;
      несуществующий рецепт → `FileNotFoundError`, `app.yaml` прежний, файла состояния нет.
- [x] A9. «Headless-бэкенд + отдельно запущенный GUI»: строго последовательно два
      `subprocess.run([sys.executable, "-c", код], cwd=<корень репо>, env={**os.environ, "PYTHONPATH": <корень>, "PYTHONUTF8": "1"}, timeout=60, check=True, capture_output=True)`.
      Процесс 1 зовёт `persist_pipeline_choice`; процесс 2 читает прототипный `load_manifest` и печатает JSON
      `{"pipeline": ..., "origin": ...}`; путь манифеста передаётся в `-c` через `sys.argv`; тест разбирает JSON →
      `pipeline == str((tmp_path/"recipes"/"b.yaml").resolve())`, `origin == "state"`.

#### C21.1 — Acceptance criteria (A10–A19)
- [x] A10. Два манифеста в разных каталогах → запись через один не меняет состояние другого.
      A10b: `app.yaml` и `stand.yaml` в одном каталоге → `app.state.yaml` и `stand.state.yaml` независимы.
- [x] A11. `mp.get_context("spawn")`, функция верхнего уровня; 2 процесса по 30 `set_pipeline` с уникальными значениями,
      старт по общему `mp.Event` → `exitcode == 0` у обоих; `safe_load(state)["pipeline"]` входит в множество записанных; нет `*.tmp.*`.
- [x] A12. `subprocess.run(["git","check-ignore","-q","multiprocess_prototype/app.state.yaml"], cwd=<корень>).returncode == 0`.
- [x] A13. Поток-писатель (`set_pipeline` по кругу из двух значений) + поток-читатель (прототипный `load_manifest` по кругу)
      2 с, оба в daemon-потоках с join-дедлайном; оба файла рецептов созданы → ноль исключений в обоих потоках;
      каждое прочитанное `pipeline` входит в {два пути} ∪ {умолчание из `app.yaml`}; за 2 с есть ≥ 1 чтение с `origin == "state"`.
- [x] A14. Состояние `{"pipeline": "backend/topology/x.yaml"}` (файл создан), `recipes: recipes` →
      `_resolve_pipeline(app, "phone_sketch") == app.recipes / "phone_sketch.yaml"`.
- [x] A15. `monkeypatch.setattr("multiprocess_prototype.main.build_launcher", lambda *a, **k: None)`; вызвать
      `_prototype_launcher_factory(types.SimpleNamespace(source=<tmp app.yaml>), None, headless=True)`; `capsys.readouterr().err`:
      битое состояние → содержит `[run]` и `app.state.yaml`; валидное → `источник: состояние`; без состояния — ни того ни другого.
- [x] A16. `monkeypatch.chdir(tmp_path)`; значение X через `ManifestStore(Path("app.yaml")).set_pipeline`, значение Y через
      абсолютный путь → `[p.name for p in tmp_path.glob("*.state.yaml")] == ["app.state.yaml"]`, `safe_load(...)["pipeline"] == Y`.
- [x] A17. Состояние `recipes/b.yaml` + `update({"pipeline": "recipes/c.yaml"})` → `load_manifest.pipeline` — b, origin `state`;
      без состояния → c, origin `manifest`; `read_raw()["pipeline"] == "recipes/c.yaml"` в обоих случаях.
- [x] A19. `SystemBuilder(AppSpec(manifest_path=p))._print_banner(load_manifest(p), n_plugins=0, n_services=0, n_processes=0)` + `capsys`:
      при валидном состоянии вывод содержит `pipeline : b.yaml (state)`, без состояния — `pipeline : a.yaml` без `(state)`.
- [x] A18 (ручная, стадия 3, не pytest). Положить `multiprocess_prototype/app.state.yaml` с `pipeline: backend/topology/hello_world.yaml`
      (файл есть, вне `recipes/`); прогнать через машинный гейт 9 модулей из DESIGN 9 → тот же passed/failed, что без файла.
      До DESIGN 6 — красные (`FileNotFoundError` на `backend/topology/<имя>.yaml`). Файл удалить.

#### C21.1 — Границы, стенд, открытое
**Out of scope:** перенос других ключей `app.yaml` в состояние; команда «сделать текущий рецепт умолчанием»;
правка `app.yaml` и рецептов; C-30 (писатель файлов рецептов из GUI); горячая смена рецепта (план 2026-10-12, 2.0);
UNC/сетевые пути в состоянии (stat мёртвого хоста может висеть — политика не задана).

**Live stand (стадия 4):** копия `app.yaml` во временном каталоге не нужна — это и есть проверка.
`run.py letter_robot_sim --headless` в worktree → `git status --short multiprocess_prototype/app.yaml` пусто,
`app.state.yaml` содержит `recipes/letter_robot_sim.yaml`, `backend_ctl capabilities` показывает процессы рецепта.
Потом отдельный старт без аргумента → тот же рецепт, stderr `источник: состояние`, `app.yaml` по-прежнему чистый.

**Открыто:** состояние молча (только лог) перебивает правку умолчания в `app.yaml` — так задумано вариантом (б);
команды «сделать умолчанием» нет.
