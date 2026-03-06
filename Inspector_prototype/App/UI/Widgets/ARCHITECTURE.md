# Widget — Архитектура

## Ответственность
**Предметно-ориентированные вкладки**. Каждый виджет — это одна функциональная вкладка главного окна.
Виджеты собирают `Components` (слайдеры, чекбоксы, таблицы) и взаимодействуют с менеджерами через явные вызовы или сигналы.
Виджеты **не владеют** менеджерами — менеджеры передаются извне (из `MainWindow`).

---

## Виджеты

| Папка | Класс | Ответственность |
|-------|-------|-----------------|
| `ImagePanel/` | `ImagePanelWidget` | Центральная панель: отображение кадра + колонки чекбоксов (Draw, Camera, Robot) через `CheckboxControlEnhanced` → `RegistersManager` |
| `Sort_widjet/` | `SortWidget`, `SortController`, `SortData`, `SortExcelExporter` | Управление рецептами/сортами: таблица параметров (0–21), применение/сохранение, Excel-экспорт |
| `Hikvision_widjet/` | `HikvisionWidget` | Управление камерой Hikvision: перечисление, открытие/закрытие, захват, параметры, FPS |
| `Visual_config_widget/` | `VisualConfigWidget` | Настройки отображения: масштаб, fullscreen-ограничения, сохранение/сброс конфигурации |
| `Visual_settings_widjet/` | `VisualSettingsWidget` | Дублирует часть `VisualConfigWidget` + кнопки debug-отчётов (legacy) |
| `Processing_widjet/` | `ProcessingWidget` | Вкладка обработки изображения: выбор камеры/региона, цепочка процессоров, HSV-слайдеры, обрезка |
| `Post_processing_widjet/` | `PostProcessingWidget` | Вкладка регионов: таблица регионов с CRUD, редактирование координат, переключение режима просмотра |
| `Circle_widjet/` | `CircleWidget` | Параметры HoughCircles: `SliderControlEnhanced` → поля `DrawRegisters` |
| `Robot_widjet/` | `RobotWidget` | Управление роботом: слайдеры и чекбоксы для параметров робота (legacy, не Enhanced) |
| `Neuroun_widjet/` | `NeurounWidget` | Управление нейросетью: чекбокс включения, порог уверенности, режимы (legacy) |
| `Parameters_widjet/` | `ParametersWidget` | Расширенная legacy-вкладка параметров: HSV, режимы, обрезка, калибровка |
| `Cropped_area_widjet/` | `CroppedAreaWidget` | Конфигурация области обрезки: слайдеры для координат и частоты конвейера |
| `Logging_widget/` | `LoggingWidget` | Кнопки управления логированием: генерация debug-отчёта, открытие папки логов |

---

## Внутренняя структура Sort_widjet

```
Sort_widjet/
  SortWidget        — только UI: таблица, кнопки, сигналы applied/saved/default
  SortController    — контроллер: связывает SortWidget ↔ ParamsManager ↔ RegistersManager
  SortData          — YAML-хранилище рецептов (без UI)
  SortExcelExporter — экспорт/импорт рецептов в Excel (без UI)
```

`SortController` живёт в `Widget/Sort_widjet/`, потому что он координирует взаимодействие
конкретного `SortWidget` с `ParamsManager`. Сам `ParamsManager` — в `Core/Managers/`.

---

## Правила

- Виджет **не создаёт** менеджеры — получает их в конструкторе или через `set_*` методы.
- Виджет может читать/писать значения через `RegistersManager`, но не обращается к `DataManager` напрямую — только через сигналы или явно переданный экземпляр.
- **Новые виджеты** должны использовать `*Enhanced`-компоненты и `RegistersManager` вместо прямого хранения состояния.
- Legacy-виджеты (`Robot`, `Neuroun`, `Parameters`, `CroppedArea`) используют базовые `SliderControl`/`CheckboxControl` — при рефакторинге переводить на `Enhanced`.
