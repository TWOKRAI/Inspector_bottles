"""Hazard-тесты автора Task 2.3 (перенос стека слоёв в `layer_render.layers`).

Только то, что видно из устройства переноса и чего нет в приёмке тестера:
  * H1 обёртка ставит read-only на результат `compose_layers` — результат не должен делить память
    с входным спрайтом, иначе `LayeredObject` заморозил бы кэш фабрики/массив вызывающего;
  * H2 `forced_defects` — `Iterable`: генератор читается дважды (проверка неизвестных и розыгрыш),
    функция обязана материализовать его один раз;
  * H3 порядок проверок при нескольких поломках сразу (дубли раньше неизвестного дефекта,
    неизвестный дефект раньше розыгрыша — rng не тронут);
  * H4 `label` в тексте — по умолчанию пустая метка, а не `None`/исключение;
  * H5 `layer_render` в рантайме не тянет `line_sim` (граница слоёв: `line_sim` → `layer_render`, не наоборот);
  * H7 `forced_defects` строкой — `TypeError` до любых проверок и до `spawn` (иначе строка разобралась бы по буквам);
  * H6 алиас `LayeredObject._transform` — тот же объект, что `transform_layer`, и на «как есть» отдаёт сам спрайт
    (кэш фабрики: `ObjectFactory.nominal_layers` оборачивает ответ read-only видом без копии).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from Services.layer_render.layers import LayerSpec, compose_layers, transform_layer

_ROOT = Path(__file__).resolve().parents[3]


def _sprite(h: int = 6, w: int = 4, value: int = 200) -> np.ndarray:
    s = np.zeros((h, w, 4), dtype=np.uint8)
    s[:, :, :3] = value
    s[:, :, 3] = 255
    return s


def test_h1_layered_object_readonly_does_not_freeze_the_input_sprite():
    """Ловит: `compose_layers`, отдающий входной спрайт (путь «как есть») вместо новой канвы —
    тогда `rgba.flags.writeable = False` в обёртке замораживает чужой массив."""
    from Services.line_sim.core.layered_object import LayeredObject
    from Services.line_sim.interfaces import ObjectPassport

    sprite = _sprite()
    layer = LayerSpec(name="base", mode="static", sprite_source=sprite)
    passport = ObjectPassport(object_id="o", class_name="c", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    obj = LayeredObject(passport, [layer], np.random.default_rng(1))

    assert obj.render().flags.writeable is False
    assert sprite.flags.writeable is True
    assert not np.shares_memory(obj.render(), sprite)


def test_h2_forced_defects_generator_is_consumed_once_and_still_forces():
    """Ловит: `forced_defects` без материализации — генератор исчерпан проверкой неизвестных,
    розыгрыш видит пустоту, и p=0 слой молча не включается."""
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite()),
        LayerSpec(name="scratch", mode="defect", sprite_source=_sprite(2, 2, 10), defect_probability=0.0),
    ]
    out = compose_layers(layers, np.random.default_rng(3), 0.0, (n for n in ["scratch"]), label="g")
    assert out.active_defects == ("scratch",)
    assert out.layer_params["scratch"] == {"active": True}


def test_h3_duplicates_are_reported_before_unknown_forced_defect():
    layers = [
        LayerSpec(name="a", mode="static", sprite_source=_sprite()),
        LayerSpec(name="a", mode="static", sprite_source=_sprite()),
    ]
    with pytest.raises(ValueError, match=r"^LayeredObject 'L': имена слоёв повторяются \['a'\]"):
        compose_layers(layers, np.random.default_rng(0), 0.0, ["nope"], label="L")


def test_h3_unknown_forced_defects_listed_in_given_order_and_rng_untouched():
    """Ловит: проверку неизвестного дефекта после `rng.spawn` (родительский rng сдвинут на ошибке)
    и потерю порядка/части неизвестных имён в тексте."""
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite()),
        LayerSpec(name="d", mode="defect", sprite_source=_sprite(), defect_probability=0.5),
    ]
    rng = np.random.default_rng(7)
    # `spawn` двигает не поток бит-генератора, а счётчик детей SeedSequence — его и сверяем.
    before = rng.bit_generator.seed_seq.n_children_spawned
    with pytest.raises(ValueError) as e:
        compose_layers(layers, rng, 0.0, ["zz", "d", "aa"], label="L")
    assert str(e.value) == "LayeredObject 'L': defect=['zz', 'aa'] — нет таких defect-слоёв (есть: ['d'])"
    assert rng.bit_generator.seed_seq.n_children_spawned == before == 0


def test_h4_default_label_is_empty_quotes():
    with pytest.raises(ValueError) as e:
        compose_layers([], np.random.default_rng(0))
    assert str(e.value) == "LayeredObject '': пустой список слоёв — нечего рисовать"


def test_h4_transparent_result_raises_after_the_draw_with_label():
    """Прозрачный итог проверяется ПОСЛЕ розыгрыша (как в прежнем `__init__`): rng сдвинут на один spawn."""
    clear = np.zeros((4, 4, 4), dtype=np.uint8)
    rng = np.random.default_rng(5)
    with pytest.raises(ValueError) as e:
        compose_layers([LayerSpec(name="x", mode="static", sprite_source=clear)], rng, label="T")
    assert str(e.value) == "LayeredObject 'T': итоговый RGBA полностью прозрачен"
    assert rng.bit_generator.seed_seq.n_children_spawned == 1


def test_h5_layer_render_import_does_not_pull_line_sim_or_dataset_gen():
    """Ловит: обратный импорт (`layers.py` → `line_sim.interfaces` ради `ObjectPassport`) или возврат
    импорта `composite`/`rotate_expand` через `dataset_gen.core.compose`. Отдельный процесс: в этом
    процессе `line_sim` уже загружен соседними тестами."""
    code = (
        "import sys, Services.layer_render, Services.layer_render.layers\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('Services.line_sim', 'Services.dataset_gen')))\n"
        "print(bad)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"


def test_h6_layered_object_transform_alias_is_transform_layer_and_keeps_identity():
    from Services.line_sim.core.layered_object import LayeredObject

    sprite = _sprite()
    assert LayeredObject._transform is transform_layer
    assert LayeredObject._transform(sprite, 1.0, 0.0, 0.0, None) is sprite
    assert LayeredObject._transform(sprite, 1.0, 0.0, 0.0, (1, 2, 3)) is not sprite


@pytest.mark.parametrize(
    ("forced", "layer_names"),
    [("scratch", ("base", "scratch")), ("d", ("base", "d"))],
    ids=["word-split-into-letters", "one-letter-layer-silently-forced"],
)
def test_h7_forced_defects_as_bare_string_is_type_error_and_rng_untouched(forced, layer_names):
    """Ловит: `list(forced_defects)` на строке — `"scratch"` даёт буквы (ложный «неизвестный дефект»),
    а `"d"` при слое `d` молча включает дефект. Значение в текст не эхуется."""
    base, defect = layer_names
    layers = [
        LayerSpec(name=base, mode="static", sprite_source=_sprite()),
        LayerSpec(name=defect, mode="defect", sprite_source=_sprite(2, 2, 10), defect_probability=0.0),
    ]
    rng = np.random.default_rng(11)
    with pytest.raises(TypeError) as e:
        compose_layers(layers, rng, 0.0, forced, label="X")
    assert str(e.value).startswith("LayeredObject 'X': forced_defects — последовательность имён")
    assert repr(forced) not in str(e.value)
    assert rng.bit_generator.seed_seq.n_children_spawned == 0
