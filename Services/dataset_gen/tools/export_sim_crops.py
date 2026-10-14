"""Экспорт обучающих вырезов из пресета слоёв с секцией `train` (CLI).

Purpose:
    Строит каталог `train/val` обучающих вырезов из пресета слоёв (`LayerSceneGenerator`, секция `train`
    пресета) и, по желанию, сетку-превью. Формат каталога — `export_splits` (`<сплит>/images/<индекс класса 000>/*.png`
    и `<сплит>/labels.csv`); его читает `Services.ml_train` при `data.source: exported`.

Public API:
    main(argv: list[str] | None = None) -> int

Запуск из корня репозитория:
    python -m Services.dataset_gen.tools.export_sim_crops \\
        --config <пресет.yaml> --out <каталог> --train 100 --val 20 [--seed 0] [--preview <сетка.png>]

Stability: lite

Контракт `main` — в его докстринге.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pydantic
import yaml

from Services.dataset_gen.core.layer_scene import LayerSceneGenerator
from Services.dataset_gen.export import export_splits
from Services.dataset_gen.preview import save_preview_grid

_PREVIEW_COUNT = 16
_PREVIEW_COLUMNS = 4


def _positive_int(text: str) -> int:
    """Тип аргумента argparse: целое >= 1."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"ожидалось целое число, получено {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"ожидалось целое >= 1, получено {value}")
    return value


def _non_negative_int(text: str) -> int:
    """Тип аргумента argparse: целое >= 0 (`default_rng` не берёт отрицательное зерно)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"ожидалось целое число, получено {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"ожидалось целое >= 0, получено {value}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_sim_crops",
        description="Экспорт обучающих вырезов (train/val) из пресета слоёв с секцией train.",
    )
    parser.add_argument("--config", required=True, help="YAML-пресет слоёв с секцией train")
    parser.add_argument("--out", required=True, help="выходной каталог (несуществующий или пустой)")
    parser.add_argument("--train", required=True, type=_positive_int, help="кадров на класс в train")
    parser.add_argument("--val", required=True, type=_positive_int, help="кадров на класс в val")
    parser.add_argument("--seed", type=_non_negative_int, default=0, help="зерно генератора (по умолчанию 0)")
    parser.add_argument("--preview", help="PNG сетки-превью 4x4 (опционально)")
    return parser


def _format_error(loc: str, msg: str) -> str:
    """`<поле>: <сообщение>`; пустой путь поля (ошибка уровня модели) — только сообщение."""
    return f"{loc}: {msg}" if loc else msg


def _load_generator(config: str, seed: int) -> LayerSceneGenerator:
    """Генератор из пресета; любая ошибка пресета -> `SystemExit('<путь>: <тип>: <причина>')`."""
    try:
        return LayerSceneGenerator.from_yaml(config, seed=seed)
    except pydantic.ValidationError as exc:  # первым: подкласс ValueError
        # Без input_value: эхо входа в текст ошибки не идёт (правило 6.2).
        errors = exc.errors(include_input=False, include_url=False)
        reason = "; ".join(_format_error(".".join(map(str, err["loc"])), err["msg"]) for err in errors)
        raise SystemExit(f"{config}: {type(exc).__name__}: {reason}") from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"{config}: {type(exc).__name__}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Разобрать аргументы, загрузить пресет, записать `train`/`val` и (опционально) сетку-превью.

    Pre: `--out` — несуществующий или пустой каталог; `--train`, `--val` >= 1; `--seed` >= 0.
    Post: успех -> код 0, по строке на сплит в stdout.
      Ошибка загрузки пресета -> `SystemExit('<путь>: <тип>: <причина>')`, в `--out` не записано ничего.
      Занятый `--out` -> `SystemExit('export_sim_crops: --out ...: <путь>')`, до загрузки пресета.
      Ошибка на кадре (например, сторона выреза больше 4000 px) -> исключение и частично записанный `--out`
      (известное ограничение, plans/layer-render/phase-6-task-6.3.md, «Открыто»).
    """
    args = _build_parser().parse_args(argv)

    # Порядок обязателен: проверка --out -> загрузка пресета -> запись. До успешной загрузки файлы не пишутся.
    out = Path(args.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise SystemExit(f"export_sim_crops: --out должен быть пустым или несуществующим каталогом: {args.out}")

    generator = _load_generator(args.config, args.seed)

    paths = export_splits(generator, out, {"train": args.train, "val": args.val}, seed=args.seed)

    if args.preview:
        # Свой поток: экспорт идёт на default_rng((seed, имя сплита)) и от превью не зависит.
        save_preview_grid(
            generator,
            args.preview,
            n=_PREVIEW_COUNT,
            cols=_PREVIEW_COLUMNS,
            rng=np.random.default_rng(args.seed),
        )

    for name, frames in (("train", args.train), ("val", args.val)):
        print(f"{name}: {frames * generator.num_classes} сэмплов -> {paths[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
