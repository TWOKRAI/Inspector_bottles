# PR3 — Permissions Rollout (миграция существующих вкладок)

> **Положение в roadmap:** PR3 из 4. Зависит от [PR2](02-pr2-login-admin.md). Следующий — [PR4](04-pr4-audit-hardening.md).
> **Контекст и общие контракты** — см. [00-metaplan.md](00-metaplan.md).

## Context

После PR2 у нас есть login и админ-панель, но **существующие вкладки не знают про permissions**.
PR3 — инкрементальная миграция: каждая вкладка декларирует свои permissions и применяет их.

Делаем **инкрементально**, не одним большим коммитом: сначала инфраструктура (TabFactory читает,
фильтрует), потом one-by-one добавляем permissions в каждую вкладку. Каждая вкладка — отдельный
sub-PR / коммит, можно ревьюить и катить независимо.

## Goals

- `TabFactory` читает `current_user.permissions`, фильтрует TAB_ORDER по `tabs.<id>.view`.
- Подписка на `auth/current_user` — при смене пользователя вкладки динамически пере-фильтровываются.
- Все существующие вкладки декларируют permissions при `register_all_tabs()`.
- Внутренние секции/кнопки критичных вкладок (Settings, Services) защищены `<scope>.edit` пермишеном.

## Non-goals

- Field-level permissions (остаётся числовой `legacy_required_level`).
- Audit (PR4).

## Files

**Изменить:**
- [multiprocess_prototype/frontend/tab_factory.py](../../../multiprocess_prototype/frontend/tab_factory.py) — фильтрация по permissions.
- [multiprocess_prototype/frontend/widgets/tabs/__init__.py](../../../multiprocess_prototype/frontend/widgets/tabs/__init__.py) — `register_all_tabs()` регистрирует permissions.
- Каждая вкладка в `multiprocess_prototype/frontend/widgets/tabs/*/tab.py` — добавляет permissions checks ключевым кнопкам/секциям.

## Steps

1. **Инфраструктура (один коммит):**
   - `TabFactory.create_tabs(...)` принимает `permissions: frozenset[str]`, фильтрует TAB_ORDER по `tabs.<id>.view`.
   - Подписка на `auth/current_user` → пересоздание `tab_widget` (или скрытие через `QTabBar.setTabVisible`).
2. **Регистрация permissions (один коммит):**
   - В `register_all_tabs()` для каждой вкладки вызывается `PermissionsRegistry.register("tabs.<id>.view", ...)` и `"tabs.<id>.edit"`.
   - Применяется ко всем 8 вкладкам (`settings`, `recipes`, `services`, `processing`, `pipeline`, `sources`, `tabs_setting`, `chrome`).
3. **Per-tab миграция (по одному коммиту на вкладку):**
   - Внутри вкладки кнопки «Сохранить», «Удалить» получают `required_edit_permission`.
   - Виды/секции, доступные только админу (например, `Settings → Системные настройки`), — `required_view_permission`.
4. **Предустановленные роли получают permissions:**
   - `admin`: все `tabs.*.view` + все `tabs.*.edit` + `users.*`, `roles.*`.
   - `operator`: `tabs.pipeline.*`, `tabs.processing.*`, `tabs.sources.view`, `tabs.recipes.*`, `tabs.settings.view`.
   - `viewer`: все `*.view`, никаких `*.edit`.
5. **Smoke-тестирование под каждой ролью:** login as viewer → проверка что edit-кнопки disabled и полупрозрачны.

## Definition of Done

- [ ] Login as `viewer` → все edit-кнопки disabled+opacity 0.5.
- [ ] Login as `operator` → settings показан, но edit-кнопки в нём disabled.
- [ ] Login as `admin` → всё доступно.
- [ ] Login as `dev` → доступна и dev-роль/dev-юзер в админке.
- [ ] `/sentrux-diff` — без деградации.

## Risks

- **Большой объём мелких правок** — много вкладок. Митигация: инкрементальные коммиты, по одной вкладке.
- **Регрессия в существующих smoke** — некоторая кнопка случайно скрыта. Митигация: smoke-чек-лист на admin-роли.

## Rollback

- Per-tab миграция откатывается per-commit.
- Инфраструктурный коммит откатывается — TabFactory возвращается к `create_tabs()` без фильтрации.
