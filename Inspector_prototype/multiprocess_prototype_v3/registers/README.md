# `multiprocess_prototype_v2/registers`

Эта папка **заморожена по составу**: только текущие файлы схем пайплайна (pipeline, camera, region, rect, renderer, processings и т.д.).

**Не добавляйте** сюда новые подпакеты, фабрики `RegistersManager`, каталоги GUI-команд или отдельные «вкладочные» схемы — это уходит в `multiprocess_prototype_v2/app_registers/`.

Причина: разделить канонические Pydantic-схемы региона/пайплайна и прикладной слой синхронизируемых регистров UI/backend.
