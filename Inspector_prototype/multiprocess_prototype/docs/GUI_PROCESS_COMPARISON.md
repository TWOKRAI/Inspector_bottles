# Сравнение GuiProcess и GuiProcessFrontend

## Обзор

| Аспект | GuiProcess | GuiProcessFrontend |
|--------|------------|---------------------|
| Создание окна | Прямое `InspectorWindow(...)` | Фабрика через `WindowManager.register()` |
| Регистры | Опционально `FrontendManager` | `ApplicationCoordinator` → `FrontendManager` → `FrontendRegistersBridge` |
| Конфиг | `dict` из `get_config("config")` | `FrontendManager.get_config()`, поддержка hot-reload |
| QTimer | В `run()` после создания окна | В фабрике окна при создании |
| Строк кода | ~404 | ~290 (дублирование gui_* вынесено) |

## Оценка в баллах (0–10)

| Критерий | GuiProcess | GuiProcessFrontend | Δ |
|----------|------------|---------------------|---|
| **Архитектура** | 6 | 8 | +2 |
| **Интеграция с фреймворком** | 5 | 9 | +4 |
| **Расширяемость** | 5 | 8 | +3 |
| **Тестируемость** | 5 | 7 | +2 |
| **Дублирование кода** | 6 | 4 | -2 |
| **Простота/читаемость** | 8 | 6 | -2 |
| **Итого (среднее)** | **5.8** | **7.0** | **+1.2** |

### Комментарии

**Архитектура (+2):** GuiProcessFrontend использует Coordinator → FrontendManager → WindowManager. Единая точка входа, разделение ответственности.

**Интеграция с фреймворком (+4):** Полный стек frontend_module: регистры, connection_map, config, возможность hot-reload. GuiProcess только частично подключает FrontendManager.

**Расширяемость (+3):** Добавление окон, потоков, виджетов — через регистрацию. Конфиг из ConfigManager. GuiProcess требует правок в `run()`.

**Тестируемость (+2):** Coordinator и FrontendManager можно мокать. Фабрика окна инжектируется. GuiProcess жёстко создаёт окно в `run()`.

**Дублирование кода (-2):** gui_* методы и _handle_* скопированы в GuiProcessFrontend. Имеет смысл вынести в общий миксин или базовый класс.

**Простота/читаемость (-2):** GuiProcess — линейный `run()`. GuiProcessFrontend — несколько слоёв (Coordinator, фабрика, регистрация). Для новичка GuiProcess проще.

## Рекомендации

1. **Вынести gui_* и _handle_* в миксин** — `GuiProcessMixin` для обоих вариантов.
2. **Оставить оба варианта** — GuiProcess для простых сценариев, GuiProcessFrontend для полной интеграции.
3. **По умолчанию** — GuiProcess (проще). GuiProcessFrontend — через `INSPECTOR_USE_FRONTEND=1`.

## Переключение

```bash
# Обычный GuiProcess
python multiprocess_prototype/main.py

# GuiProcessFrontend (стек frontend_module)
INSPECTOR_USE_FRONTEND=1 python multiprocess_prototype/main.py
```
