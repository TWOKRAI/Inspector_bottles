# frontend/managers — менеджеры уровня frontend-приложения

Единое место для сервисов, которые живут в процессе frontend и переиспользуются вкладками
и точкой входа (`FrontendLauncher`). Все менеджеры регистрируются в `FrontendAppContext`
и получаются вкладками через `get_*()`-аксессоры контекста (Dict at Boundary на границах).

## Состав

| Менеджер | Файл | Назначение |
|----------|------|------------|
| `RecipeManager` | `recipe_manager.py` | YAML-хранилище рецептов регистров + app-пресетов. Два файла: `data/recipes.yaml`, `data/settings_recipes.yaml`. Протокол — `recipe_manager_protocol.py`. |
| `SettingsProfileManager` | `settings_profile_manager.py` | Phase 0. Профили настроек приложения (camera_count, ring_buffer_size, shm_budget_mb и т.д.) в `data/settings_profiles.yaml`. `switch_profile` применяет снимок через `RegistersManager.model_validate_all`, предварительно валидируя SHM-бюджет (AD-6 → `ShmBudgetError`). Протокол — `settings_profile_protocol.py`. |
| `SettingsYamlStore` | `settings_yaml_store.py` | Изолированный класс persistence для `SettingsProfileManager`. Формат файла: `{version, current_profile, profiles: {id: snapshot}}`. Тестируется отдельно от бизнес-логики. |

## Паттерн подключения

```python
# FrontendLauncher.register_windows()
from multiprocess_prototype.frontend.managers import (
    RecipeManager, SettingsProfileManager,
)

recipe_manager = RecipeManager(data_path=config.get("recipes_path"))
settings_profile_manager = SettingsProfileManager(
    data_path=config.get("settings_profiles_path"),
)
if regs is not None:
    settings_profile_manager.ensure_default_profile(regs)

app_ctx = FrontendAppContext(
    ...,
    recipe_manager=recipe_manager,
    settings_profile_manager=settings_profile_manager,
)
```

Вкладка получает менеджера из контекста:

```python
def __init__(self, ctx: FrontendAppContext, ...):
    self._settings = ctx.settings_profile_manager
```

## Тесты

| Уровень | Файлы |
|---------|-------|
| L1 unit | `tests/unit/test_settings_yaml_store.py`, `tests/unit/test_settings_profile_manager.py`, `tests/unit/test_frontend_integration_settings.py`, `tests/unit/test_frontend_config_settings_path.py` (требует PyQt5) |
| L2 integration | `tests/test_settings_profile_switch.py` — сценарии A/B/C/D (YAML → switch → RegistersManager) |

Запуск из корня ``:

```bash
pytest multiprocess_prototype/tests/unit/ -v
pytest multiprocess_prototype/tests/test_settings_profile_switch.py -v
```

## Связь с планом

Реализация Phase 0 из `plans/prototype_v3_expansion.md` и `plans/phase_0_tasks.md`.
Последующие фазы (Phase 2 — UI-таб профилей, Phase 3 — чтение профиля для динамической
оркестрации камер) зависят от `SettingsProfileManager` и регистра `settings`.
