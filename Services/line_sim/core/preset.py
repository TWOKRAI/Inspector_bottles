"""ScenePreset — конфиг сцены (Pydantic v2), dict/YAML на границе.

По образцу `Services.dataset_gen.core.config.GeneratorConfig`. На dict-границе
`sprite_source` — строка-идентификатор (загрузка спрайта — `ObjectFactory` из
`catalog_bridge`, Task 3.2). `ScenePreset` сам картинок не читает (Dict at Boundary,
LS-007) — каталог классов грузит `ObjectFactory`, здесь только путь и диапазоны.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from Services.line_sim.interfaces import LayerSpec


class ScenePreset(BaseModel):
    """Пресет сцены: каталог классов и/или дополнительные слои объекта.

    Pre (from_dict): хотя бы одно из `catalog_dir`/`layers` задано (иначе нечего
    рисовать); в `layers` `sprite_source` — строка-id; `angle_range_deg`: lo <= hi.
    Post: `from_dict(p.to_dict()) == p`, `from_yaml(to_yaml(p)) == p`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_dir: str | None = None
    angle_range_deg: tuple[float, float] = (0.0, 360.0)
    defect_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    layers: list[LayerSpec] = Field(default_factory=list)

    @field_validator("angle_range_deg")
    @classmethod
    def _angle_range_order(cls, value: tuple[float, float]) -> tuple[float, float]:
        lo, hi = value
        if lo > hi:
            raise ValueError(f"angle_range_deg: lo={lo} > hi={hi}")
        return value

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

    @model_validator(mode="after")
    def _catalog_or_layers(self) -> ScenePreset:
        if self.catalog_dir is None and not self.layers:
            raise ValueError("пресет без catalog_dir и без layers: нечего рисовать — нужен хотя бы один источник")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenePreset:
        """Создать пресет из dict; ошибки — pydantic.ValidationError с именем слоя и поля.

        Относительные пути (catalog_dir, sprite_source доп. слоёв) НЕ резолвятся здесь —
        это делает только `from_yaml` (нет базового каталога, от которого мерить)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (кортежи → списки)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScenePreset:
        """Загрузить пресет из YAML-файла.

        Относительные `catalog_dir` и `sprite_source` доп. слоёв резолвятся от каталога
        файла — тот же паттерн, что `GeneratorConfig.from_dict(..., base_dir)`
        (`Services.dataset_gen.core.config`)."""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Пресет {p}: ожидался YAML-словарь, получено {type(data).__name__}")
        return cls.from_dict(_resolve_relative_paths(data, base_dir=p.parent))

    def to_yaml(self, path: str | Path) -> None:
        """Записать пресет в YAML (комментарии не сохраняются — ruamel придёт с редактором Ф7)."""
        text = yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)
        Path(path).write_text(text, encoding="utf-8")


def _resolve_relative_paths(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Относительные `catalog_dir`/`layers[*].sprite_source` -> абсолютные строки от base_dir."""
    resolved = dict(data)

    catalog_dir = resolved.get("catalog_dir")
    if isinstance(catalog_dir, str) and _looks_like_relative_path(catalog_dir):
        resolved["catalog_dir"] = str((base_dir / catalog_dir).resolve())

    layers = resolved.get("layers")
    if isinstance(layers, list):
        resolved_layers = []
        for layer in layers:
            if isinstance(layer, dict):
                source = layer.get("sprite_source")
                if isinstance(source, str) and _looks_like_relative_path(source):
                    layer = {**layer, "sprite_source": str((base_dir / source).resolve())}
            resolved_layers.append(layer)
        resolved["layers"] = resolved_layers

    return resolved


def _looks_like_relative_path(value: str) -> bool:
    """Отличить настоящий относительный путь файловой системы от opaque id-строки
    (например `"fixture://base"` в тестах 3.1 — там `sprite_source` не путь, а id
    для callable-подмены в тесте, резолвить его нельзя). `"://"` — маркер схемы id;
    у обычных путей (в т.ч. с `../`) его не бывает."""
    return "://" not in value and not Path(value).is_absolute()
