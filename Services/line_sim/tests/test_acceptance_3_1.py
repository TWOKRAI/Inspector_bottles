"""Независимые acceptance-тесты Task 3.1 + 3.1a — движок объектов line_sim.

Написаны ДО реализации (RED-фаза, tester не видел `_impl/`/Steps плана). Источник
истины — критерии приёмки `plans/line-sim/phase-3-object-engine.md` (Task 3.1) и
`plans/line-sim/phase-3a-layer-contract.md` (Task 3.1a), НЕ код под тестом.

Публичный контракт (из Files/Fields плана):
    from Services.line_sim import ObjectPassport, LayerSpec, LayerAugment, LayeredObject, ScenePreset
    from Services.line_sim.core.belt import encoder_to_offset_mm
    FACTOR_MM импортируется из Services.robot_comm.core.registers (не хардкодится).

================================================================================
ПРЕДПОЛОЖЕНИЯ О СИГНАТУРАХ (план оставляет их открытыми — реализация выравнивается
сюда; каждое — явная догадка, не факт из плана):
================================================================================

- ObjectPassport(object_id, class_name, angle_deg, defect, spawn_encoder,
                  layer_params: dict[str, dict] = {}) — dataclass, kwargs.
  `layer_params` — задел под AC 3.1a "layer_params в паспорте содержит фактически
  выбранные значения аугментации"; ключ — имя слоя, значение — словарь применённых
  параметров (`offset_x_px`, `angle_deg`, ...).

- LayerSpec(name, mode, sprite_source, offset_px=(0.0, 0.0), angle_deg=0.0,
            scale=1.0, augment: LayerAugment | None = None,
            defect_probability: float = 0.0) — dataclass, kwargs.
  `sprite_source` в тестах ниже — ЛИБО сырой RGBA np.ndarray, ЛИБО callable без
  аргументов `() -> np.ndarray` (нужен для подсчёта обращений в тесте "рендер
  один раз"). План явно разрешает оба варианта ("может быть in-memory array или
  callable provider").
  `defect_probability` — имя поля ДОГАДКА: план называет только "вероятность" у
  слоя в режиме defect, имя атрибута не даёт. Если у реализации оно другое —
  teamlead поправит вызов в тесте `test_defect_prob_bounds`, сам факт наличия
  такого параметра остаётся acceptance-требованием.

- LayerAugment(offset_x_px=(0,0), offset_y_px=(0,0), angle_deg=(0,0), scale=(1,1),
               hue_shift_deg=(0,0)) — dataclass/pydantic, kwargs, все дефолты
  вырождены (см. Fields в phase-3a).

- LayeredObject(passport: ObjectPassport, layers: list[LayerSpec],
                rng: np.random.Generator) — конструктор делает ВСЮ выборку
  аугментации/дефекта сразу (Task 3.1a step 1: "один раз, при создании объекта").
  `.render()` — БЕЗ аргументов, возвращает закэшированный RGBA np.ndarray
  (идемпотентен — "повторный render() возвращает тот же массив без повторной
  компоновки"). ЭТО ОСОЗНАННОЕ РАСХОЖДЕНИЕ с Files исходного Task 3.1, где
  сигнатура была `render(rng) -> np.ndarray` — сам план в 3.1a требует
  пересмотреть эту сигнатуру под свойство "выборка один раз при создании", и
  вызов render(rng) после создания создавал бы вторую точку случайности, что
  прямо противоречит AC "побитово идентичен между кадрами". Если реализация
  всё же держит `render(rng)` — вызовы `obj.render()` ниже упадут с TypeError,
  это будет явный сигнал разработчику поправить сигнатуру или сообщить тестеру.
  `obj.passport` — атрибут, содержащий (возможно, дополненный layer_params)
  паспорт после конструирования.

- ScenePreset — Pydantic-конфиг, `from_dict`/`to_dict`/`from_yaml`/`to_yaml`.
  Форма словаря НЕ описана в плане подробно (только "каталог классов, диапазон
  углов, список слоёв-дефектов + вероятности") — ниже используется МИНИМАЛЬНАЯ
  придуманная форма: {"layers": [{...LayerSpec-поля...}]}, где sprite_source
  внутри словаря — СТРОКА (opaque id/путь), а не ndarray (Dict at Boundary,
  правило #1 CLAUDE.md: на границе — только сериализуемые значения; реальная
  загрузка спрайта по строке — предмет Task 3.2, не Task 3.1). Это ДРУГОЙ путь
  создания LayerSpec, чем прямая Python-конструкция с ndarray/callable выше.

================================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from Services.line_sim import (
    LayerAugment,
    LayeredObject,
    LayerSpec,
    ObjectPassport,
    ScenePreset,
)
from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.robot_comm.core.registers import FACTOR_MM

# --------------------------------------------------------------------------
# Общие помощники (см. блок предположений выше — здесь их конкретные формы)
# --------------------------------------------------------------------------


def _passport(
    angle_deg: float = 0.0,
    defect: str | None = None,
    spawn_encoder: float = 0.0,
    object_id: str = "obj-1",
    class_name: str = "letter_a",
) -> ObjectPassport:
    return ObjectPassport(
        object_id=object_id,
        class_name=class_name,
        angle_deg=angle_deg,
        defect=defect,
        spawn_encoder=spawn_encoder,
    )


def _marker_sprite(channel: int, size: int = 5) -> np.ndarray:
    """Маленький непрозрачный RGBA-квадрат-маркер одного чистого канала (0=R, 2=B)."""
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    lo, hi = 1, size - 1
    sprite[lo:hi, lo:hi, channel] = 220
    sprite[lo:hi, lo:hi, 3] = 255
    return sprite


def _solid_opaque_sprite(size: int = 5) -> np.ndarray:
    """Насыщенный красный непрозрачный спрайт — под hue-shift (серый не годится:
    поворот тона у серого/белого визуально ничего не меняет)."""
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    sprite[:, :, 0] = 200
    sprite[:, :, 3] = 255
    return sprite


class _CountingSprite:
    """Callable-провайдер спрайта, считающий обращения — наблюдаемый эффект
    для проверки "рендер один раз" (не спай на имя приватного метода)."""

    def __init__(self, rgba: np.ndarray) -> None:
        self._rgba = rgba
        self.calls = 0

    def __call__(self) -> np.ndarray:
        self.calls += 1
        return self._rgba


def _centroid(rgba: np.ndarray, color_mask) -> tuple[float, float]:
    """Взвешенный центроид (x, y) непрозрачных пикселей, прошедших color_mask."""
    mask = color_mask(rgba) & (rgba[:, :, 3] > 0)
    ys, xs = np.nonzero(mask)
    assert xs.size > 0, "маркер не найден на кадре — сломан тест, а не движок"
    return float(xs.mean()), float(ys.mean())


def _marker_vector(rgba: np.ndarray) -> tuple[float, float]:
    """Вектор (dx, dy) от красного якоря (offset всегда (0,0)) к синему маркеру."""
    ax, ay = _centroid(rgba, lambda a: (a[:, :, 0] > 150) & (a[:, :, 2] < 50))
    bx, by = _centroid(rgba, lambda a: (a[:, :, 2] > 150) & (a[:, :, 0] < 50))
    return bx - ax, by - ay


def _anchor_layer(offset_px: tuple[float, float] = (0.0, 0.0)) -> LayerSpec:
    # [teamlead 3.1] offset_px добавлен: в тестах сдвига маркер с offset (0,0) лёг бы
    # ровно на якорь и закрыл его целиком — якорь выносится вверх, разность векторов не меняется.
    return LayerSpec(name="anchor", mode="static", sprite_source=_marker_sprite(0), offset_px=offset_px)


def _minimal_preset_dict() -> dict:
    return {
        "layers": [
            {"name": "base", "mode": "static", "sprite_source": "fixture://base"},
        ],
    }


def _three_mode_preset_dict() -> dict:
    """Пресет с тремя слоями трёх режимов — фикстура для round-trip тестов."""
    return {
        "layers": [
            {
                "name": "base",
                "mode": "static",
                "sprite_source": "fixture://base",
                "offset_px": [0.0, 0.0],
                "angle_deg": 0.0,
                "scale": 1.0,
            },
            {
                "name": "label",
                "mode": "augmented",
                "sprite_source": "fixture://label",
                "offset_px": [0.0, 0.0],
                "angle_deg": 0.0,
                "scale": 1.0,
                "augment": {
                    "offset_x_px": [0.0, 0.0],
                    "offset_y_px": [0.0, 0.0],
                    "angle_deg": [-5.0, 5.0],
                    "scale": [1.0, 1.0],
                    "hue_shift_deg": [0.0, 0.0],
                },
            },
            {
                "name": "damage",
                "mode": "defect",
                "sprite_source": "fixture://damage",
                "offset_px": [0.0, 0.0],
                "angle_deg": 0.0,
                "scale": 1.0,
            },
        ],
    }


# --------------------------------------------------------------------------
# Task 3.1 — импорт и зависимости
# --------------------------------------------------------------------------


def test_import_has_no_heavy_optional_deps():
    """AC: импорт без обязательного torch/PySide6 (только numpy/opencv/pydantic).

    [teamlead 3.1] проверка вынесена в чистый подпроцесс: в процессе pytest PySide6
    уже загружен плагином pytest-qt (qt_api = pyside6) до сбора тестов — in-process
    проверка красна при любой реализации.
    """
    import subprocess

    code = "import sys, Services.line_sim; print('torch' in sys.modules, 'PySide6' in sys.modules)"
    root = Path(__file__).resolve().parents[3]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False"]


def test_module_docs_present():
    """AC: README.md/STATUS.md/DECISIONS.md присутствуют, README описывает контракт."""
    base = Path(__file__).resolve().parents[1]
    assert (base / "README.md").exists()
    assert (base / "STATUS.md").exists()
    assert (base / "DECISIONS.md").exists()
    readme = (base / "README.md").read_text(encoding="utf-8")
    for symbol in ("ObjectPassport", "LayerSpec", "LayeredObject", "ScenePreset"):
        assert symbol in readme


# --------------------------------------------------------------------------
# Task 3.1 — геометрия ленты
# --------------------------------------------------------------------------


def test_encoder_offset_zero_and_linear():
    """AC: encoder_to_offset_mm(enc,enc)==0; линейна с FACTOR_MM из robot_comm."""
    assert encoder_to_offset_mm(enc_now=1000, spawn_enc=1000) == pytest.approx(0.0)
    n = 250
    assert encoder_to_offset_mm(enc_now=1000 + n, spawn_enc=1000) == pytest.approx(n * FACTOR_MM)


# --------------------------------------------------------------------------
# Task 3.1 — базовый рендер и поворот объекта
# --------------------------------------------------------------------------


def test_render_single_static_layer_nonzero_alpha():
    """AC: один статический слой, angle_deg=0 -> RGBA с ненулевой альфой."""
    layer = LayerSpec(name="only", mode="static", sprite_source=_solid_opaque_sprite())
    obj = LayeredObject(
        passport=_passport(angle_deg=0.0, object_id="single"),
        layers=[layer],
        rng=np.random.default_rng(9),
    )
    frame = obj.render()
    assert frame.shape[-1] == 4
    assert np.any(frame[:, :, 3] > 0)


def test_object_rotation_changes_render_vs_zero_degrees():
    """AC: angle_deg=90 у объекта с несимметричным содержимым даёт ДРУГОЙ рендер,
    чем angle_deg=0 — поворот применяется, не игнорируется."""

    def layers():
        return [
            _anchor_layer(),
            LayerSpec(name="moved", mode="static", sprite_source=_marker_sprite(2), offset_px=(5.0, 0.0)),
        ]

    obj0 = LayeredObject(
        passport=_passport(angle_deg=0.0, object_id="rot0"), layers=layers(), rng=np.random.default_rng(3)
    )
    obj90 = LayeredObject(
        passport=_passport(angle_deg=90.0, object_id="rot90"), layers=layers(), rng=np.random.default_rng(3)
    )
    v0 = _marker_vector(obj0.render())
    v90 = _marker_vector(obj90.render())
    dist = ((v0[0] - v90[0]) ** 2 + (v0[1] - v90[1]) ** 2) ** 0.5
    assert dist > 3.0


def test_rotation_is_ccw_literal():
    """AC 3.1a (доп. 2026-09-22): несимметричный спрайт (метка справа от центра),
    angle_deg=+90 у объекта -> метка СВЕРХУ (CCW, ось Y вниз, конвенция
    cv2.getRotationMatrix2D — см. докстринг rotate_expand в dataset_gen/core/compose.py).

    Литерал выведен вручную по формуле cv2.getRotationMatrix2D (alpha=cos90=0,
    beta=sin90=1): точка (dx=+5, dy=0) относительно центра переходит в
    (dx'=0, dy'=-5) — то есть строго вверх (y уменьшается = вверх на экране).
    Не вызывает rotate_expand напрямую — это ожидание, а не вывод кода под тестом.
    """
    layers = [
        _anchor_layer(),
        LayerSpec(name="moved", mode="static", sprite_source=_marker_sprite(2), offset_px=(5.0, 0.0)),
    ]
    obj = LayeredObject(
        passport=_passport(angle_deg=90.0, object_id="ccw"), layers=layers, rng=np.random.default_rng(2)
    )
    dx, dy = _marker_vector(obj.render())
    assert dx == pytest.approx(0.0, abs=1.0)
    assert dy == pytest.approx(-5.0, abs=1.0)


# --------------------------------------------------------------------------
# Task 3.1a — offset_px / augment смещения
# --------------------------------------------------------------------------


def test_offset_px_shifts_centroid_20px_right():
    """AC: статический слой с offset_px=(20,0) -> центроид на 20±1 px правее,
    чем при offset_px=(0,0). Сравнение через вектор якорь->маркер внутри одного
    кадра — устойчиво к тому, как именно канва объекта расширяется/кадрируется."""
    obj_origin = LayeredObject(
        passport=_passport(object_id="off0"),
        layers=[
            _anchor_layer(offset_px=(0.0, -10.0)),
            LayerSpec(name="moved", mode="static", sprite_source=_marker_sprite(2), offset_px=(0.0, 0.0)),
        ],
        rng=np.random.default_rng(1),
    )
    obj_shifted = LayeredObject(
        passport=_passport(object_id="off20"),
        layers=[
            _anchor_layer(offset_px=(0.0, -10.0)),
            LayerSpec(name="moved", mode="static", sprite_source=_marker_sprite(2), offset_px=(20.0, 0.0)),
        ],
        rng=np.random.default_rng(1),
    )
    dx0, dy0 = _marker_vector(obj_origin.render())
    dx1, dy1 = _marker_vector(obj_shifted.render())
    assert dx1 - dx0 == pytest.approx(20.0, abs=1.0)
    assert dy1 - dy0 == pytest.approx(0.0, abs=1.0)


def test_augment_offset_x_range_point_shifts_centroid_10px():
    """AC: слой augmented с offset_x_px=(10,10) (диапазон-точка) -> центроид на
    10±1 px правее варианта с (0,0) — аугментация реально применяется."""

    def moved(offset_range: tuple[float, float]) -> LayerSpec:
        return LayerSpec(
            name="moved",
            mode="augmented",
            sprite_source=_marker_sprite(2),
            augment=LayerAugment(offset_x_px=offset_range),
        )

    obj_zero = LayeredObject(
        passport=_passport(object_id="augoff0"),
        layers=[_anchor_layer(offset_px=(0.0, -10.0)), moved((0.0, 0.0))],
        rng=np.random.default_rng(4),
    )
    obj_ten = LayeredObject(
        passport=_passport(object_id="augoff10"),
        layers=[_anchor_layer(offset_px=(0.0, -10.0)), moved((10.0, 10.0))],
        rng=np.random.default_rng(4),
    )
    dx0, dy0 = _marker_vector(obj_zero.render())
    dx1, dy1 = _marker_vector(obj_ten.render())
    assert dx1 - dx0 == pytest.approx(10.0, abs=1.0)
    assert dy1 - dy0 == pytest.approx(0.0, abs=1.0)


def test_augmented_degenerate_equals_static():
    """AC: слой augmented со всеми дефолтными (вырожденными) диапазонами
    рендерится ПОБИТОВО так же, как тот же слой в режиме static."""
    sprite = _solid_opaque_sprite()
    static_layer = LayerSpec(name="x", mode="static", sprite_source=sprite)
    augmented_layer = LayerSpec(name="x", mode="augmented", sprite_source=sprite, augment=LayerAugment())
    obj_static = LayeredObject(
        passport=_passport(object_id="deg_static"), layers=[static_layer], rng=np.random.default_rng(6)
    )
    obj_augmented = LayeredObject(
        passport=_passport(object_id="deg_augmented"), layers=[augmented_layer], rng=np.random.default_rng(6)
    )
    assert np.array_equal(obj_static.render(), obj_augmented.render())


def test_augment_angle_range_seed_determinism():
    """AC: angle_deg=(-30,30) — seed=1 и seed=2 дают РАЗНЫЕ рендеры; два объекта
    с seed=1 — побитово ОДИНАКОВЫЕ (выборка детерминирована и один раз)."""

    def build(seed: int, object_id: str) -> np.ndarray:
        layers = [
            _anchor_layer(),
            LayerSpec(
                name="moved",
                mode="augmented",
                sprite_source=_marker_sprite(2),
                offset_px=(6.0, 0.0),
                augment=LayerAugment(angle_deg=(-30.0, 30.0)),
            ),
        ]
        obj = LayeredObject(passport=_passport(object_id=object_id), layers=layers, rng=np.random.default_rng(seed))
        return obj.render()

    r1a = build(1, "seed1a")
    r1b = build(1, "seed1b")
    r2 = build(2, "seed2")
    assert np.array_equal(r1a, r1b)
    assert not np.array_equal(r1a, r2)


def test_hue_shift_changes_rgb_not_alpha():
    """AC: hue_shift_deg=(90,90) меняет RGB непрозрачных пикселей и НЕ меняет
    альфа-канал (побитовое сравнение альфы)."""

    def build(hue_range: tuple[float, float]) -> np.ndarray:
        layer = LayerSpec(
            name="painted",
            mode="augmented",
            sprite_source=_solid_opaque_sprite(),
            augment=LayerAugment(hue_shift_deg=hue_range),
        )
        obj = LayeredObject(
            passport=_passport(object_id=f"hue_{hue_range}"), layers=[layer], rng=np.random.default_rng(5)
        )
        return obj.render()

    base = build((0.0, 0.0))
    shifted = build((90.0, 90.0))
    assert np.array_equal(base[:, :, 3], shifted[:, :, 3])
    assert not np.array_equal(base[:, :, :3], shifted[:, :, :3])


def test_layer_params_recorded_in_passport():
    """AC: layer_params в паспорте содержит фактически выбранные значения — для
    диапазона-точки (10,10) там должно лежать именно 10.0."""
    layer = LayerSpec(
        name="moved",
        mode="augmented",
        sprite_source=_marker_sprite(2),
        augment=LayerAugment(offset_x_px=(10.0, 10.0)),
    )
    passport = _passport(object_id="lp")
    obj = LayeredObject(passport=passport, layers=[layer], rng=np.random.default_rng(8))
    obj.render()
    recorded = obj.passport.layer_params["moved"]
    assert recorded["offset_x_px"] == pytest.approx(10.0)


# --------------------------------------------------------------------------
# Task 3.1a — рендер один раз (кэш)
# --------------------------------------------------------------------------


def test_render_is_cached_once():
    """AC: объект рендерится при создании и кэшируется; повторный render() не
    вызывает повторную загрузку/компоновку спрайта — проверка по наблюдаемому
    эффекту (счётчик обращений к sprite_source), не по имени приватного метода.
    Заодно покрывает AC "один и тот же объект, отрендеренный дважды — побитово
    идентичен"."""
    provider = _CountingSprite(_solid_opaque_sprite())
    layer = LayerSpec(name="cached", mode="static", sprite_source=provider)
    obj = LayeredObject(passport=_passport(object_id="cache"), layers=[layer], rng=np.random.default_rng(7))

    first = obj.render()
    calls_after_first = provider.calls
    second = obj.render()

    assert provider.calls == calls_after_first, "повторный render() не должен заново грузить/компоновать спрайт"
    assert np.array_equal(first, second)


# --------------------------------------------------------------------------
# Task 3.1 — дефект-слой с вероятностью (границы, не середина)
# --------------------------------------------------------------------------


def _defect_prob_object(probability: float, seed: int) -> LayeredObject:
    base = LayerSpec(name="base", mode="static", sprite_source=_marker_sprite(0))
    defect = LayerSpec(name="damage", mode="defect", sprite_source=_marker_sprite(2), defect_probability=probability)
    return LayeredObject(
        passport=_passport(object_id=f"defect_{seed}"), layers=[base, defect], rng=np.random.default_rng(seed)
    )


def test_defect_prob_bounds():
    """AC: defect_probability=1.0 -> 20/20 объектов заменяют базовый слой
    (синий маркер поверх красного, по z-order defect поверх static);
    defect_probability=0.0 -> 0/20. Только границы, не середина диапазона."""
    replaced_at_1 = sum(1 for seed in range(20) if np.any(_defect_prob_object(1.0, seed).render()[:, :, 2] > 150))
    replaced_at_0 = sum(1 for seed in range(20) if np.any(_defect_prob_object(0.0, seed).render()[:, :, 2] > 150))
    assert replaced_at_1 == 20
    assert replaced_at_0 == 0


# --------------------------------------------------------------------------
# Task 3.1 / 3.1a — валидация и граничные случаи (Edge cases)
# --------------------------------------------------------------------------


def test_layered_object_empty_layers_raises_value_error():
    """Edge case: пустой список слоёв в LayeredObject — ValueError с понятным текстом."""
    with pytest.raises(ValueError):
        LayeredObject(passport=_passport(object_id="empty"), layers=[], rng=np.random.default_rng(0))


def test_layer_without_alpha_raises_explicit_error():
    """Edge case: слой без альфа-канала (RGB вместо RGBA) — явная ошибка на
    загрузке, не тихий крэш глубже по стеку. Тип исключения план не называет —
    проверяем сам факт явного отказа где-то в конструировании/рендере."""
    rgb_only = np.zeros((9, 9, 3), dtype=np.uint8)
    with pytest.raises(Exception):
        layer = LayerSpec(name="no_alpha", mode="static", sprite_source=rgb_only)
        obj = LayeredObject(passport=_passport(object_id="no_alpha"), layers=[layer], rng=np.random.default_rng(0))
        obj.render()


def test_augment_on_non_augmented_layer_raises():
    """Edge case: augment задан у слоя не в режиме augmented — ошибка валидации
    (тихо проигнорированный диапазон хуже отказа)."""
    with pytest.raises(Exception):
        LayerSpec(
            name="mislabeled",
            mode="static",
            sprite_source=_solid_opaque_sprite(),
            augment=LayerAugment(angle_deg=(-10.0, 10.0)),
        )


def test_augment_range_lo_gt_hi_raises_named_validation_error():
    """AC: диапазон с lo > hi — ошибка валидации при загрузке пресета, с именем
    слоя и поля в тексте, а не ValueError из недр rng.uniform."""
    preset_dict = {
        "layers": [
            {
                "name": "broken_layer",
                "mode": "augmented",
                "sprite_source": "fixture://broken",
                "augment": {
                    "offset_x_px": [0.0, 0.0],
                    "offset_y_px": [0.0, 0.0],
                    "angle_deg": [30.0, -30.0],  # намеренно lo > hi
                    "scale": [1.0, 1.0],
                    "hue_shift_deg": [0.0, 0.0],
                },
            },
        ],
    }
    with pytest.raises(Exception) as exc_info:
        ScenePreset.from_dict(preset_dict)
    message = str(exc_info.value)
    assert "broken_layer" in message
    assert "angle_deg" in message


# --------------------------------------------------------------------------
# Task 3.1 / 3.1a — ScenePreset: создание, round-trip
# --------------------------------------------------------------------------


def test_scene_preset_from_dict_minimal_valid():
    """AC: ScenePreset.from_dict({...минимальный валидный конфиг...}) создаётся
    без исключения."""
    preset = ScenePreset.from_dict(_minimal_preset_dict())
    assert preset is not None


def test_scene_preset_from_dict_empty_raises_validation_error():
    """AC: ScenePreset.from_dict({}) (пустой) бросает понятную ошибку валидации
    (Pydantic), а не падает на непонятном AttributeError ниже по стеку."""
    with pytest.raises(Exception):
        ScenePreset.from_dict({})


def test_preset_dict_round_trip():
    """AC: ScenePreset.from_dict(p.to_dict()) == p для пресета с тремя слоями
    трёх режимов."""
    preset = ScenePreset.from_dict(_three_mode_preset_dict())
    assert ScenePreset.from_dict(preset.to_dict()) == preset


def test_preset_yaml_round_trip(tmp_path):
    """AC (доп. 2026-09-22): from_yaml(to_yaml(p)) == p через файл во временном
    каталоге."""
    preset = ScenePreset.from_dict(_three_mode_preset_dict())
    yaml_path = tmp_path / "preset.yaml"
    preset.to_yaml(yaml_path)
    assert ScenePreset.from_yaml(yaml_path) == preset
