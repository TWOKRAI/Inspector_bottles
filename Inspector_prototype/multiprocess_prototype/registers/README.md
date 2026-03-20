# Регистры прототипа Inspector

Доменные схемы регистров живут в **`schemas/`** (по фичам, напр. `schemas/processing_tab/`) и наследуют `SchemaBase` из `data_schema_module`. Это код приложения, не фреймворка. Подписи экранов без `register_update` — рядом с виджетом во `frontend/widgets/<feature>/`.

- Фабрика: `factory.py` → `RegistersManager` + `connection_map`
- Чеклист нового поля: `CHECKLIST.md`
- Значения по умолчанию для boot `proc_dict` процессов (синхронно с регистрами): `schemas/processing_tab/boot.py` (`processor_process_boot_values`, `renderer_process_boot_values`)

См. **ADR-050** в `multiprocess_framework/refactored/DECISIONS.md`.
