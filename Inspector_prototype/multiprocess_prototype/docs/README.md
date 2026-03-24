# Документация multiprocess_prototype

Здесь только **актуальные** описания, совпадающие с текущим кодом. История решений — в [`DECISIONS.md`](../../multiprocess_framework/refactored/DECISIONS.md); черновики планов в этом каталоге не хранятся.

| Документ | Содержание |
|----------|------------|
| **[../README.md](../README.md)** | Запуск, тесты, переменные окружения |
| **[../STATUS.md](../STATUS.md)** | Состояние прототипа, ограничения |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Процессы, SHM, регистры, GUI, оценки; ссылки на фреймворк |
| **[FRONTEND_MAP.md](FRONTEND_MAP.md)** | Цепочка UI: лаунчер → FrontendManager → окно → вкладки; `FrontendAppContext`; команды |
| **[RECIPES_SYSTEM.md](RECIPES_SYSTEM.md)** | Два вида рецептов в одном YAML, `RecipeManager`, вкладки, конфиг |

**Рядом с кодом (не в `docs/`):**

| Путь | Назначение |
|------|------------|
| [../registers/README.md](../registers/README.md) | Схемы регистров, factory, routing |
| [../persistence/README.md](../persistence/README.md) | Данные приложения, user_prefs |
| [../managers/README.md](../managers/README.md) | RecipeManager, AccessContext, app-агрегат |

**Фреймворк:** [`ARCHITECTURE_MODULE_CATALOG.md`](../../multiprocess_framework/refactored/docs/ARCHITECTURE_MODULE_CATALOG.md) · [`FRONTEND_COMMAND_LAUNCHER_ROADMAP.md`](../../multiprocess_framework/refactored/docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md) · [`refactored/README.md`](../../multiprocess_framework/refactored/README.md)
