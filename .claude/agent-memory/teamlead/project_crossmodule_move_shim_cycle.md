---
name: project-crossmodule-move-shim-cycle
description: Перенос schema-модуля между framework-модулями + back-compat шим ловит runtime circular import через eager package __init__ re-export
metadata:
  type: project
---

Перенос модуля (напр. `blueprint.py`) из одного framework-подмодуля в другой с back-compat
шимом на старом пути ловит **runtime circular import**, если старый пакетный `__init__.py`
ЖАДНО реэкспортит перенесённые символы.

Механизм (C6 c, blueprint из process_module/generic → process_manager_module/topology):
`generic/__init__` → шим(blueprint) → `topology.blueprint` → `process_module.plugins.port`
→ `plugins/__init__` → `generic.generic_process_config` → `generic/__init__` (re-entrant,
шим ещё не готов) → ImportError partially initialized.

**Как чинить:** убрать пакетный re-export из `__init__.py` (оставить символы доступными
только через подмодуль `.blueprint`/шим напрямую). Грепни `from ..X import <Symbol>` —
если из ПАКЕТА никто не импортит (только из подмодуля), удаление re-export безопасно.

**Why:** впереди ещё carve-outs (см. [[project_arch_boundaries_plan]] — план границ C1-C8);
тот же паттерн повторится при любом cross-module переносе schema/контракта с шимом.

**How to apply:** при переносе с шимом — проверь оба порядка импорта свежим интерпретатором
(`python -c "import new; import old_shim"` и наоборот) ДО прогона тестов; sentrux dsm
cycles_change это НЕ ловит (шим-ребро между framework-подмодулями не флагается как цикл).
