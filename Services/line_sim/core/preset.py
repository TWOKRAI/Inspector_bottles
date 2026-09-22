"""ScenePreset — конфиг сцены (Pydantic v2), dict/YAML на границе.

По образцу `Services.dataset_gen.core.config.GeneratorConfig`. На dict-границе
`sprite_source` — строка-идентификатор (загрузка спрайта по id — Task 3.2).
Каталог классов и диапазон углов объекта добавит Task 3.2 вместе с каталогом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from Services.line_sim.interfaces import LayerSpec


class ScenePreset(BaseModel):
    """Пресет сцены: список слоёв объекта.

    Pre (from_dict): `layers` — непустой список словарей-слоёв; `sprite_source` — строка.
    Post: `from_dict(p.to_dict()) == p`, `from_yaml(to_yaml(p)) == p`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    layers: list[LayerSpec] = Field(min_length=1)

    @field_validator("layers")
    @classmethod
    def _sprite_ids_only(cls, layers: list[LayerSpec]) -> list[LayerSpec]:
        for layer in layers:
            if not isinstance(layer.sprite_source, str):
                raise ValueError(f"слой '{layer.name}': в пресете sprite_source должен быть строкой-id")
        names = [layer.name for layer in layers]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"имена слоёв повторяются: {dupes}")
        return layers

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenePreset:
        """Создать пресет из dict; ошибки — pydantic.ValidationError с именем слоя и поля."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (кортежи → списки)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScenePreset:
        """Загрузить пресет из YAML-файла."""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Пресет {p}: ожидался YAML-словарь, получено {type(data).__name__}")
        return cls.from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        """Записать пресет в YAML (комментарии не сохраняются — ruamel придёт с редактором Ф7)."""
        text = yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)
        Path(path).write_text(text, encoding="utf-8")
