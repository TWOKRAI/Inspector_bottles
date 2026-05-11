"""Schema-фасад для frontend_module.

Единая точка реэкспорта схем-примитивов из data_schema_module, через которую
frontend_module/* (виджеты, формы, чейн-генератор) получает SchemaBase,
FieldMeta, register_schema, FieldRouting, RegisterDispatchMeta.

Зачем:
- frontend_module — крупный потребитель data_schema_module (~22 файла).
  Без фасада каждый widget/schema.py висел собственным cross-module edge
  на data_schema_module, что разрывало DSM-кластер и тянуло modularity вниз.
- Внутри одного top-level модуля sentrux группирует файлы в общий кластер;
  единый адаптер сводит все edges frontend → data_schema_module к одному
  файлу-границе, не меняя API.

Никаких frontend-specific надстроек тут НЕТ — это чистый pass-through.
Если потребуется адаптер с UI-логикой (например, FieldMeta → QWidget),
он живёт отдельно (forms/, components/) и НЕ должен подмешиваться сюда,
иначе фасад превратится в смешение слоёв.
"""

from __future__ import annotations

from .. import data_schema_module as _ds

SchemaBase = _ds.SchemaBase
FieldMeta = _ds.FieldMeta
FieldRouting = _ds.FieldRouting
RegisterDispatchMeta = _ds.RegisterDispatchMeta
register_schema = _ds.register_schema

__all__ = [
    "SchemaBase",
    "FieldMeta",
    "FieldRouting",
    "RegisterDispatchMeta",
    "register_schema",
]
