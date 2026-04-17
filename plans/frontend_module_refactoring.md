# План: Рефакторинг frontend_module

**Статус:** DONE  
**Дата:** 2026-04-17  
**Scope:** `Inspector_prototype/multiprocess_framework/modules/frontend_module/`  
**Ограничение:** документация + очистка, без изменения публичного API

---

## Контекст

frontend_module — ~10,000 LOC, 175 файлов, 5 слоёв (application, core, components, widgets, schemas+configs).
Модуль остаётся внутри фреймворка. Цель — навести порядок, чтобы новый проект мог за 30 минут поднять GUI.

## Задачи

### 1. README.md — quick-start для нового проекта
- Как подключить frontend_module
- Как создать MainWindow (HeaderWidget + ImagePanelWidget + TabWidget)
- Как создать свой виджет (BaseWidget[TModel] паттерн)
- Как привязать виджет к регистрам (RegisterBindingContext)
- Примеры кода

### 2. STATUS.md — текущее состояние
- Что работает, что в TODO

### 3. Очистить components/examples/
- ~20 файлов учебных примеров внутри production-кода
- Вынести в docs/examples/ или удалить если дублируют тесты

### 4. Ревизия interfaces.py
- ~221 LOC протоколов для всех слоёв
- Убедиться что актуальны, убрать неиспользуемые

### 5. Ревизия LegacySyncTrait
- Проверить использование в old prototype и v3
- Удалить если не используется

### 6. Проверить __init__.py экспорты
- Все публичные экспорты актуальны

## Что использует old prototype
~75 файлов. Основные: FrontendLaunchHooks, run_process_attached_frontend, BaseWidget, HeaderWidget, TabWidget, ImagePanelWidget, TabPresenterBase, RegisterBindingContext, NumericControl, CheckboxControl, SliderControl, RoutedCommandSender, BindingConfig, qt_imports.

## Что использует v3 prototype
FrontendLaunchHooks, run_process_attached_frontend, HeaderWidget, TabWidget, ImagePanelWidget, qt_imports, LoadingWindow.

## Результаты выполнения

### 1. README.md — ПЕРЕПИСАН
Quick-start с реальными примерами: FrontendLaunchHooks, run_process_attached_frontend, BaseWidget[TModel], RegisterBindingContext. Структура модуля, таблица реально используемого API.

### 2. STATUS.md — ПЕРЕПИСАН
Актуальные оценки, чеклист, результаты ревизии всех 4 подзадач.

### 3. components/examples/ — ОСТАВЛЕНЫ
8 пакетов используются тестом `test_example_with_data_schema.py`. Прототипы не импортируют. Перенос сломает тесты без выгоды.

### 4. interfaces.py — ВСЕ АКТИВНЫ
5 протоколов (IControlView, INumericView, IFieldBinding, IRegisterPort, RegistersManagerLike) — все используются presenter-ами и фасадами. Удалять нечего.

### 5. LegacySyncTrait — СОХРАНЁН
Не используется прототипами пока, но механизм может понадобиться. Оставлен без изменений.

### 6. __init__.py — ОЧИЩЕН
19 → 5 экспортов. Оставлены: FrontendLaunchHooks, run_process_attached_frontend, FrontendManager, RoutedCommandSender, WindowManager. Остальное доступно через подпакеты. Версия → 0.3.0.

### Дополнительно: кандидаты на вынос из прототипов
- `FrontendLauncher` — базовый класс (дублируется в old и v3)
- QTimer polling boilerplate — `attach_process_timers()` хелпер
- `FrontendAppContext` — базовый контейнер зависимостей
- `create_loading_window` — дефолтная фабрика

## Ограничения
- НЕ перемещать модуль из multiprocess_framework
- НЕ менять публичный API
- НЕ рефакторить внутреннюю логику компонентов
- Python 3.9+, PyQt5
