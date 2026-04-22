# Чеклист: новое поле алгоритма / новый контрол на главном окне

Используйте для вкладок `MainWindow` и связанных виджетов (обработка, настройки отображения и т.д.).

1. **StateRegister** — добавить поле в соответствующий пакет `multiprocess_prototype/registers/schemas/<feature>/` (`ProcessorRegisters`, `RendererRegisters`, …) с `FieldMeta` (диапазоны, `routing`, при необходимости `process_targets`).
2. **Файл схемы** — один канон в `registers/schemas/`, без копии во фреймворке.
3. **UiSchema** — подписи/группы без доставки в процессы: у вкладки в `frontend/widgets/<feature>/schemas.py` (напр. `processing_tab/schemas.py` — `ProcessingTabUiConfig`).
4. **Виджет** — контрол с `register_name` / `field_name` и `registers_manager` (или явная передача из `tab_factory` / `MainWindow`).
5. **Backend** — процесс-получатель обрабатывает `register_update` для этого поля (см. ADR-048, `ROUTING_GLOSSARY.md`) или явный мост на существующую команду.
6. **Проверка** — `python scripts/validate.py`, pytest для затронутых модулей.

См. **ADR-049** в `multiprocess_framework/DECISIONS.md` (StateRegister vs UiSchema).

Вложенные поля **`processor.crop_regions`** / **`post_processing_regions`**: канон и миграции — **`docs/DATA_MODEL_NESTED.md`**, код — `registers/schemas/processing_tab/crop_regions_payload.py`, `post_processing_payload.py`.
