"""Метаданные/разметка классов: файл `meta.yaml` в папках каталога классов.

В каждой папке каталога классов (на любом уровне вложенности) может лежать
опциональный `meta.yaml` (или `meta.yml` / `meta.json`) — разметка этого
узла. Метаданные НАСЛЕДУЮТСЯ сверху вниз: значения родительской папки
применяются к подклассам, дочерний файл переопределяет родительский.

Зачем:
  - переопределить симметрию класса рядом с его данными (а не в глобальном
    конфиге) — `symmetry: none|180|full`;
  - задать человекочитаемое имя `display_name`;
  - повесить произвольную разметку (теги, артикул, цвет, что угодно) — она
    сохраняется в реестр `classes.json` при экспорте и доступна обучающему коду.

Известные поля валидируются, всё остальное складывается в `extra` как есть.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from Services.dataset_gen.core.config import SymmetryType

META_FILENAMES = ("meta.yaml", "meta.yml", "meta.json")


class ClassMeta(BaseModel):
    """Разметка узла каталога классов (одного файла meta.*).

    Все поля опциональны. Неизвестные ключи допускаются и собираются в `extra`.
    """

    model_config = ConfigDict(extra="allow")

    display_name: str | None = None
    symmetry: SymmetryType | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @property
    def extra(self) -> dict[str, Any]:
        """Произвольные (неизвестные схеме) поля из файла."""
        return self.__pydantic_extra__ or {}

    def merged_with_child(self, child: ClassMeta) -> ClassMeta:
        """Слить с дочерним узлом: непустые поля ребёнка переопределяют родителя.

        Pre:
          - child — метаданные более глубокого узла
        Post:
          - display_name/symmetry/description берутся у ребёнка, если заданы;
            tags ребёнка заменяют родительские, если непусты;
            extra сливается по ключам (ребёнок переопределяет)
        """
        data: dict[str, Any] = {
            "display_name": child.display_name or self.display_name,
            "symmetry": child.symmetry or self.symmetry,
            "description": child.description or self.description,
            "tags": child.tags or self.tags,
        }
        merged_extra = {**self.extra, **child.extra}
        return ClassMeta(**data, **merged_extra)

    def to_dict(self) -> dict[str, Any]:
        """Плоский dict разметки на границе (для classes.json)."""
        d: dict[str, Any] = {
            "display_name": self.display_name,
            "symmetry": self.symmetry,
            "description": self.description,
            "tags": list(self.tags),
        }
        d.update(self.extra)
        return d


def load_meta(directory: Path) -> ClassMeta:
    """Прочитать meta.* из папки (первый найденный по META_FILENAMES).

    Pre:
      - directory существует
    Post:
      - пустой ClassMeta, если файла нет; ValueError при битом файле
    """
    for name in META_FILENAMES:
        path = directory / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        if raw is None:
            return ClassMeta()
        if not isinstance(raw, dict):
            raise ValueError(f"Метаданные {path}: ожидался словарь, получено {type(raw).__name__}")
        return ClassMeta.model_validate(raw)
    return ClassMeta()


def write_meta(directory: Path, meta: ClassMeta) -> Path:
    """Записать meta.yaml в папку (служебные None-поля опускаются)."""
    payload = {k: v for k, v in meta.to_dict().items() if v not in (None, [], {})}
    path = directory / "meta.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
