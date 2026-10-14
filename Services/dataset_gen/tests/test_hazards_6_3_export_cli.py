# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 6.3: CLI `Services/dataset_gen/tools/export_sim_crops.py` и секция `train` боевого пресета.

Приёмку пишет слепой тестер (`test_acceptance_6_3_export_cli.py`); здесь — порядок действий и побочные эффекты:
что CLI не пишет в `--out` до загрузки конфига и не трогает чужие файлы, что превью не влияет на экспорт, что боевой
пресет читается без каталога `data/`, что в файле CLI нет слов продукта. Фикстуры продукта P берутся из файла приёмки
(синтетика numpy -> PNG во `tmp_path`); ожидаемые значения — литералы.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from Services.dataset_gen.tests.test_acceptance_6_3_export_cli import (
    _export,
    _files,
    _hashes,
    _main,
    _product_p,
)

_ROOT = Path(__file__).resolve().parents[3]
_CLI_FILE = _ROOT / "Services" / "dataset_gen" / "tools" / "export_sim_crops.py"
_BATTLE_PRESET = _ROOT / "Services" / "line_sim" / "presets" / "letters_layered.yaml"


def _argv(config: str, out: Path, *extra: str, train: str = "2", val: str = "1", seed: str = "3") -> list[str]:
    return ["--config", config, "--out", str(out), "--train", train, "--val", val, "--seed", seed, *extra]


# H1 ------------------------------------------------------------------------------------------------------------------


def test_h1_nonempty_out_refused_and_untouched(tmp_path: Path) -> None:
    """Непустой `--out` -> `SystemExit` с путём в тексте; чужой файл цел, новых файлов нет."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out"
    out.mkdir()
    foreign = out / "x.txt"
    foreign.write_bytes(b"keep-me")

    with pytest.raises(SystemExit) as info:
        _main(_argv(config, out))

    assert isinstance(info.value.code, str)
    assert str(out) in info.value.code
    assert foreign.read_bytes() == b"keep-me"
    assert _files(out) == {"x.txt"}


def test_h1_out_is_a_file_refused(tmp_path: Path) -> None:
    """`--out` — существующий файл (не каталог) -> `SystemExit`, файл цел."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out.bin"
    out.write_bytes(b"data")

    with pytest.raises(SystemExit) as info:
        _main(_argv(config, out))

    assert isinstance(info.value.code, str)
    assert str(out) in info.value.code
    assert out.read_bytes() == b"data"


def test_h1_empty_existing_out_accepted(tmp_path: Path) -> None:
    """Пустой существующий `--out` годится: экспорт проходит, файлы появились."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out"
    out.mkdir()

    assert _main(_argv(config, out)) == 0
    assert "train/labels.csv" in _files(out)


# H2 ------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--train", "--val"])
def test_h2_zero_frames_is_argparse_error(flag: str, tmp_path: Path) -> None:
    """`--train 0` и `--val 0` -> `SystemExit(2)` (argparse); `--out` не создан."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out"
    kwargs = {"train": "0"} if flag == "--train" else {"val": "0"}

    with pytest.raises(SystemExit) as info:
        _main(_argv(config, out, **kwargs))

    assert info.value.code == 2
    assert not out.exists()


def test_h2_negative_seed_is_argparse_error(tmp_path: Path) -> None:
    """`--seed -1` -> `SystemExit(2)`, `--out` не создан (`default_rng` не берёт отрицательное зерно)."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as info:
        _main(_argv(config, out, seed="-1"))

    assert info.value.code == 2
    assert not out.exists()


# H3 / H4 -------------------------------------------------------------------------------------------------------------


def test_h3_preview_does_not_change_export(tmp_path: Path) -> None:
    """Тот же `--seed` с превью и без: каталоги `--out` побайтно равны.

    Ни один мутант этот тест не краснит: свойство выполняется по построению (превью идёт после экспорта, у
    экспорта свой rng от `(seed, имя сплита)`). Защита от превью на rng без зерна — H4 (E7); превью на
    внутреннем rng генератора — эквивалентный мутант.
    """
    config = _product_p(tmp_path / "prod")
    plain = tmp_path / "plain"
    with_preview = tmp_path / "with_preview"

    assert _export(config, plain, 3, 1, 5) == 0
    assert _export(config, with_preview, 3, 1, 5, "--preview", str(tmp_path / "grid.png")) == 0

    assert len(_hashes(plain)) == 2 + 3 * 2 + 1 * 2  # 2 csv + 6 train + 2 val: литерал, не из кода
    assert _hashes(plain) == _hashes(with_preview)


def test_h4_preview_bytes_repeatable(tmp_path: Path) -> None:
    """Два прогона с одним `--seed`: PNG-сетки побайтно равны; другой `--seed` даёт другую сетку."""
    config = _product_p(tmp_path / "prod")
    grids = []
    for name, seed in (("a", 7), ("b", 7), ("c", 8)):
        grid = tmp_path / f"grid_{name}.png"
        assert _export(config, tmp_path / f"out_{name}", 2, 1, seed, "--preview", str(grid)) == 0
        grids.append(hashlib.sha256(grid.read_bytes()).hexdigest())

    assert grids[0] == grids[1]
    assert grids[0] != grids[2]  # якорь: сетка вообще зависит от зерна


# H5 ------------------------------------------------------------------------------------------------------------------


def test_h5_battle_preset_train_section_valid_without_data() -> None:
    """Секция `train` боевого пресета проходит `TrainSection`; путь тайла от каталога пресета -> `<корень>/data/...`.

    Файлы `data/` не читаются: проверяется только схема и разрешение пути.
    """
    from Services.dataset_gen.core.layer_scene import TrainSection  # noqa: PLC0415
    from Services.layer_render.preset import ScenePreset  # noqa: PLC0415

    preset = ScenePreset.from_yaml(_BATTLE_PRESET)
    assert preset.train is not None
    section = TrainSection.model_validate(preset.train)

    assert section.symmetry.overrides == {"Х": "180"}  # "180" строкой, не int
    tiles = [layer["tile"] for layer in section.background_layers if "tile" in layer]
    assert len(tiles) == 1
    expected = _ROOT / "data" / "line_sim" / "belt_tile.png"
    assert Path(preset.resolve_path(tiles[0])).resolve() == expected.resolve()


# H6 ------------------------------------------------------------------------------------------------------------------


def test_h6_no_product_words_in_cli_file() -> None:
    """В файле CLI нет слов продукта (докстринг, help, комментарии, тексты ошибок): тот же шаблон, что `rg -in`."""
    text = _CLI_FILE.read_text(encoding="utf-8")

    assert re.search(r"letter|букв|disk|диск", text, re.IGNORECASE) is None


# H7 ------------------------------------------------------------------------------------------------------------------


def test_h7_validation_error_text_has_path_type_and_no_input_echo(tmp_path: Path) -> None:
    """Пресет без `catalog_dir` -> текст `<путь>: ValidationError: ...` без `input_value`; `--out` не создан."""
    config = _product_p(tmp_path / "prod", catalog=False)
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as info:
        _main(_argv(config, out))

    assert isinstance(info.value.code, str)
    assert info.value.code.startswith(f"{config}: ValidationError:")
    assert "input_value" not in info.value.code
    assert not out.exists()
