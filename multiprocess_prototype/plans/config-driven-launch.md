# Главный конфиг + config-driven запуск: фундамент ⊕ pipeline

> Ветка: `refactor/config-driven-launch` · Refs: plans/config-driven-launch.md
> Дубль одобренного плана Claude Code (`~/.claude/plans/drifting-waddling-fog.md`).

## Контекст

Точка входа `run.py → main.py → bootstrap` — три почти одноимённых слоя, путаница «много main()», непонятно где какая топология/конфиги. Видение владельца:

- Один **главный конфиг** (`app.yaml`) с путями к system / styles / pipeline / recipes.
- Две топологии: **приватный фундамент** (GUI/презентация + always-on) ⊕ **pipeline** (полезная нагрузка). При запуске **суммируются**.
- Базовые процессы (презентация, оркестратор) **не в pipeline**.
- Презентация **заменяема** (PyQt → веб-сервер) сменой класса в конфиге.
- **Всё на конфигах, GUI опционален**: цепочки сами = рабочее приложение (headless).

## Ключевой факт о форматах

`backend/topology/*.yaml` — **runnable** (грузится на старте, есть `plugin_class`/config/`chain_targets`/регистры). `recipes/*.yaml` — editor-state GUI-редактора (плагины как голый `plugin_name`, без рантайм-полей). Это разные роли, не дубль. **Решение (A): запуск читает runnable-формат; GUI-редактор `recipes/` остаётся отдельным editor-слоем; сведение форматов — отдельная будущая фаза.** Merge + `build_configs()` сохраняют все регистры; дизайн открыт к будущим non-plugin/standalone-регистрам.

## Целевая модель

`app.yaml`:
```yaml
system:   backend/config/system.yaml
styles:   { dir: frontend/styles/themes, active: innotech_theme }
base:     backend/topology/base.yaml             # фундамент: презентация + always-on
pipeline: backend/topology/region_pipeline.yaml  # активный запускаемый pipeline
recipes:  recipes/                               # GUI-редактируемые рецепты (editor-слой)
```
```python
def main(manifest_path=None) -> int:
    app = load_manifest(manifest_path or DEFAULT_MANIFEST)
    build_launcher(app).run()
    return 0

def build_launcher(app):
    merged = merge(load_yaml(app.base), load_yaml(app.pipeline))
    configs = SystemBlueprint.model_validate(merged).build_configs()
    ...  # + system.yaml defaults, orchestrator — как сейчас
```

## План

### Фаза 1 — Главный конфиг + чистый вход (низкий риск)
1. `app.yaml` + `load_manifest` (~30 строк рядом со `schemas.py`, 1 Pydantic-модель + функция, без нового пакета).
2. `run.py`: `main()`→`launch()`; `main.py`: тонкий `main()`, `bootstrap`→`build_launcher`(+алиас), fix докстринг, сохранить публичные `CONFIG_PATH`/`PROJECT_ROOT`/`DEFAULT_BLUEPRINT`.
3. Тема из манифеста (`theme_loader.apply_default_theme(app, theme_name)`, `app.py` читает `styles.active`).
4. Единый startup-баннер (manifest/system/base/pipeline/theme/log_dir/число процессов).
5. `[project.scripts] inspector = run:launch` + Makefile `run`.

### Фаза 2 — Фундамент ⊕ pipeline (средний риск)
6. `base.yaml` — вынести `gui` из топологий (классом + `protected`); имя `gui` пока сохранить.
7. `merge(base, pipeline)` + сборка (конкатенация processes/wires + коллизии → `build_configs`).
8. Golden-тест: `base ⊕ region_pipeline` == старый цельный `region_pipeline` (сравнивать конфиги).
9. Headless: `base` без презентации → цепочки бегут.
10. Чистка `.bak` + `*.yaml.bak` в `.gitignore`.

## Что НЕ делаем сейчас

Сведение recipe→runnable, rename `gui→ui`, горячая смена pipeline в рантайме, `display_bindings` вместо `chain_targets`, web-презентация, `active_services`-активация, write-back в манифест.

## Риски

merge (golden-тест); публичные символы `main` (алиас); ~5-6 тестов на удаление `gui`; слои импортов (backend без frontend `io.py`); GUI читает манифест в своём процессе; validate.py sys.path (run/main whitelisted).

## Проверка

`run.py` → баннер + GUI + кадры; `run.py inspection_basic` (override); тема из app.yaml; headless; `pytest multiprocess_prototype/ -q` + golden; `validate.py` + sentrux rules.
