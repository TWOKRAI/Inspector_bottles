# Стили прототипа

## Структура

| Путь | Роль |
|------|------|
| [`schemas/ui_theme.py`](schemas/ui_theme.py) | `UiThemeConfig` (SchemaBase): `global_tokens`, `bundle_overrides` — формат как у остальных конфигов |
| [`legacy_app_style.py`](legacy_app_style.py) | Тонкая обёртка: `create_legacy_app_style_session` → `frontend_module.styling.create_app_style_session` |

Шаблоны `.qss` и дефолтные токены перенесены во **фреймворк**: `frontend_module` — файлы рядом с виджетами/компонентами, реестр — `frontend_module.styling.default_bundles`, сборка сессии — `app_style_session.py`.

Секция **`ui_theme`** попадает в dict конфига (`build_frontend_config`) и в лаунчер: `create_app_style_session(ui_theme=config["ui_theme"])`.

Переопределения из `GuiConfig` / app_cfg мержатся в `FrontendConfig.build_dict` (см. `_merge_ui_theme_dict`).

## Регистры алгоритма vs тема UI

- **Регистры** (`registers/schemas`) — поля процесса, синхронизация, рецепты алгоритма.
- **Тема** — отдельная схема `UiThemeConfig`: плоские токены для QSS, сериализация в JSON/YAML рядом с `FrontendConfig`, версии рецептов UI — отдельный поток от снимков регистров.

Перевод «полей в таблице → токены» остаётся в приложении: слияние в dict → `StyleSession.refresh`.

## Legacy App

Таблица соответствия App/UI/Components — в комментариях к `StyleBundleSpec` в `frontend_module/styling/default_bundles.py`.
