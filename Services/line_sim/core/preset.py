"""ScenePreset — конфиг сцены (Pydantic v2), dict/YAML на границе.

По образцу `Services.dataset_gen.core.config.GeneratorConfig`. На dict-границе
`sprite_source` — строка-идентификатор (загрузка спрайта — `ObjectFactory` из
`catalog_bridge`, Task 3.2). `ScenePreset` сам картинок не читает (Dict at Boundary,
LS-007) — каталог классов грузит `ObjectFactory`, здесь только путь и диапазоны.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from Services.line_sim.interfaces import LayerSpec

# Имена слоёв, которые ObjectFactory ставит сама (база и дефект) — пресет их занимать
# не может, иначе make() падает на дубликате имени слоя (LayeredObject это уже проверяет,
# но ошибка должна быть на границе пресета, с понятным текстом, а не в недрах фабрики).
_RESERVED_LAYER_NAMES = frozenset({"base", "damaged"})


class ScenePreset(BaseModel):
    """Пресет сцены: каталог классов и/или дополнительные слои объекта.

    Pre (from_dict): хотя бы одно из `catalog_dir`/`layers` задано (иначе нечего
    рисовать); в `layers` `sprite_source` — строка-id; `angle_range_deg`: lo <= hi.
    Post: `from_dict(p.to_dict()) == p`; `from_yaml(to_yaml(p, f))` с `f` в каталоге `p.base_dir` равен `p`;
    при `f` в другом каталоге равенства нет (пути пересчитаны), но грузятся те же картинки.

    `base_dir` (Task 1.0, LS-013) — каталог, от которого резолвятся относительные
    `catalog_dir`/`layers[*].sprite_source` (`resolve_path()`); `None` — резолвить
    от текущего рабочего каталога процесса (поведение `ScenePreset(catalog_dir=...)`
    без файла-источника, не меняется). Путь сам по себе НЕ резолвится и не
    переписывается нигде, кроме `resolve_path()` — на dict-границе и в YAML он
    остаётся ровно той строкой, что была задана (переносимость между машинами).
    `base_dir` — настоящее поле модели (едет через `to_dict`/`from_dict`, участвует
    в равенстве), но НЕ попадает в `to_yaml()` — там его заменяет каталог целевого
    файла.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_dir: str | None = None
    angle_range_deg: tuple[float, float] = (0.0, 360.0)
    defect_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    layers: list[LayerSpec] = Field(default_factory=list)
    base_dir: str | None = None

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
        # Зарезервированные имена мешают только вместе с catalog_dir: ObjectFactory сама
        # добавляет слои "base"/"damaged" вокруг layers пресета (LS-007), и только тогда
        # имя коллидирует — до 3.2 слой "base" был легальным именем в layers-only пресете
        # (test_acceptance_3_1.py), это не трогаем.
        if self.catalog_dir is not None:
            reserved_used = sorted({layer.name for layer in self.layers if layer.name in _RESERVED_LAYER_NAMES})
            if reserved_used:
                raise ValueError(
                    f"слои {reserved_used}: имена зарезервированы ObjectFactory (база и дефект-слой "
                    f"ставятся под именами {sorted(_RESERVED_LAYER_NAMES)}) — переименуйте слои пресета"
                )
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenePreset:
        """Создать пресет из dict; ошибки — pydantic.ValidationError с именем слоя и поля.

        Пути (`catalog_dir`, `sprite_source` доп. слоёв) хранятся КАК ЕСТЬ — резолюцию
        делает только `resolve_path()`, и только в момент чтения (`ObjectFactory`),
        от `base_dir`, если тот присутствует в `data`. Здесь ничего не резолвится и не
        переписывается — dict остаётся переносимым между машинами."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (кортежи → списки); `base_dir` едет как обычное поле —
        нужен другому процессу на той же машине и для `from_dict(p.to_dict()) == p`."""
        return self.model_dump(mode="json")

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScenePreset:
        """Загрузить пресет из YAML-файла.

        Строки путей (`catalog_dir`, `sprite_source` доп. слоёв) НЕ переписываются —
        вместо этого `base_dir` пресета ставится в каталог файла (перекрывая любой
        `base_dir`, случайно оставшийся в самом YAML: место файла — источник истины).
        Резолюция происходит лениво, в `resolve_path()`, когда `ObjectFactory`
        действительно читает изображение — так пресет переживает перенос каталога
        на другую машину без потери исходных относительных строк."""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Пресет {p}: ожидался YAML-словарь, получено {type(data).__name__}")
        return cls.from_dict({**data, "base_dir": str(p.parent.resolve())})

    def resolve_path(self, value: str) -> str:
        """Строка-id или абсолютный путь -> без изменений; относительный путь ->
        абсолютный от `base_dir` (или без изменений, если `base_dir` не задан —
        тогда действует CWD процесса, как раньше у `ScenePreset(catalog_dir=...)`
        без файла-источника)."""
        if not _looks_like_relative_path(value):
            return value
        if self.base_dir is None:
            return value
        return str(Path(self.base_dir) / value)

    def to_yaml(self, path: str | Path) -> None:
        """Записать пресет в YAML (комментарии не сохраняются — ruamel придёт с редактором Ф7).

        `base_dir` в файл не пишется (это не часть переносимой конфигурации — при
        следующей загрузке его снова поставит `from_yaml`). Относительные
        `catalog_dir`/`layers[*].sprite_source` пересчитываются от каталога ЦЕЛЕВОГО
        файла (`os.path.relpath`), если у пресета есть свой `base_dir` и он отличается
        от каталога цели, — иначе строки остаются как есть. Абсолютные пути и id-схемы
        (`fixture://...`) не трогаются никогда."""
        data = self.to_dict()
        data.pop("base_dir", None)

        if self.base_dir is not None:
            # resolve(): иначе relpath от симлинка (/tmp -> /private/tmp) даёт ../../../../tmp/... (ревью 1.0)
            base_dir = Path(self.base_dir).resolve()
            target_dir = Path(path).parent.resolve()
            if base_dir.resolve() != target_dir:
                data["catalog_dir"] = self._rebase_value(data.get("catalog_dir"), base_dir, target_dir)
                layers = data.get("layers")
                if isinstance(layers, list):
                    data["layers"] = [
                        {**layer, "sprite_source": self._rebase_value(layer.get("sprite_source"), base_dir, target_dir)}
                        if isinstance(layer, dict)
                        else layer
                        for layer in layers
                    ]

        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        Path(path).write_text(text, encoding="utf-8")

    @staticmethod
    def _rebase_value(value: Any, base_dir: Path, target_dir: Path) -> Any:
        """Одна строка пути `to_yaml()` -> пересчитана от `target_dir` вместо `base_dir`.

        Не строка / не похоже на файловый путь (id-схема, абсолютный путь, None) ->
        без изменений. `os.path.relpath` падает `ValueError` на разных дисках Windows —
        # ponytail: тогда откатываемся на абсолютный путь как потолок; апгрейд —
        # pathlib.PureWindowsPath, если реально понадобится кросс-дисковый save-as.
        """
        if not isinstance(value, str) or not _looks_like_relative_path(value):
            return value
        try:
            # В YAML всегда прямые слэши: Windows-relpath даёт `..\\A\\sprites`, а Mac/Orin
            # читают такую строку как одно имя файла (замер ntpath.relpath, 2026-09-27).
            # ponytail: обратный слэш в имени файла на POSIX теряется — такие имена не ожидаются.
            return os.path.relpath(base_dir / value, target_dir).replace("\\", "/")
        except ValueError:
            return str((base_dir / value).resolve())


def _looks_like_relative_path(value: str) -> bool:
    """Отличить настоящий относительный путь файловой системы от opaque id-строки
    (например `"fixture://base"` в тестах 3.1 — там `sprite_source` не путь, а id
    для callable-подмены в тесте, резолвить его нельзя). `"://"` — маркер схемы id;
    у обычных путей (в т.ч. с `../`) его не бывает."""
    return "://" not in value and not Path(value).is_absolute()
