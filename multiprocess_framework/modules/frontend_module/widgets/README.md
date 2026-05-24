# widgets — составные UI-компоненты фреймворка

Высокоуровневые виджеты: вкладки (MVP-паттерн), таблицы, заголовок окна, виртуальная клавиатура, контролер производительности. Примитивы (слайдер, чекбокс) находятся в `components/`.

## Ключевые символы

- `BaseWidget`, `WidgetSignalBus` — базовый виджет и шина сигналов для межкомпонентного взаимодействия.
- `BaseTab`, `MvpTabBase`, `TabPresenterBase`, `TabViewProtocol` — таб-система на основе MVP (Model-View-Presenter).
- `TabWidget` — контейнер вкладок; `RegisterBindingContext` — связь вкладок с регистрами.
- `HeaderWidget`, `ButtonHeader` — заголовок окна с логотипом и кнопками администратора.
- `VirtualKeyboard`, `VirtualKeyboardMini` — экранная клавиатура для сенсорных экранов.
- `StructuredTableWidget`, `StructuredTwoLevelTreeWidget` — таблицы и иерархические деревья с toolbars.
- `PerformanceMonitor` — виджет для мониторинга производительности процессов.

## Stability

partial

→ Корневой README: `../../README.md`
