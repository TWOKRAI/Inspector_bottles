# managers — generic менеджеры для frontend-приложений

Переиспользуемые компоненты управления состоянием: конфигурация (YAML-слоты), профили настроек, темы оформления, права доступа пользователя.

## Ключевые символы

- `ConfigSnapshotManager` — YAML-хранилище именованных слотов конфигурации (register-слоты + app-слоты). API-агностичен — пути передаются снаружи.
- `ConfigSnapshotProtocol`, `RecipeManagerProtocol` — контракты для расширяемости.
- `YamlPersistenceStore` — чтение/запись профилей настроек в YAML.
- `SettingsProfileManagerProtocol` — контракт для менеджера профилей настроек.
- `ThemeManager`, `ThemePresetsManager` — управление темами оформления (светлая/тёмная/custom).
- `AccessContext` — контекст прав доступа пользователя в сессии.

## Stability

lite

→ Корневой README: `../../README.md`
