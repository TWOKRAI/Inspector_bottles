# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты layer-render Task 1.3 (уровень плагина и стенда): `background_layers` — единственный
способ задать фон `scene_source`; ключ `background_texture` удалён.

Источник контракта: `plans/layer-render/phase-1.md`, Task 1.3 (DESIGN + Acceptance A2, A3, A4, A5, A6). Написаны ДО
реализации: worktree на коммите «только план», реализации 1.3 в дереве нет.

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render` (рабочее дерево автора) и любой diff/реализация
Task 1.3. Прочитано как ГОТОВАЯ ЗАВИСИМОСТЬ: `plugin.py` (до 1.3), тесты 1.1
(`test_background_layers_acceptance_1_1.py`) и 3.6
(`test_scene_source_task_3_6.py`, `test_scene_source_hazards_3_6.py`) — источник свойств и литералов.

Происхождение литералов sha256 (повторно запинены БЕЗ изменений, не пересчитаны):
  `_GOLDEN_NO_BACKGROUND_KEY_SHA`, `_GOLDEN_BACKGROUND_TEXTURE_SHA` —
  `Plugins/sim/scene_source/tests/test_background_layers_acceptance_1_1.py:155-156` (сняты прогоном на дереве ДО
  Task 1.1). Старые тесты 3.6 sha256 НЕ пинят (только пиксели) — других sha256-литералов старого пути нет.
  Старый вход литерала: `background_texture=<RGB-тайл th=40, tw=23, seed 0>` в `_cfg` (seed 7) при серой заливке
  плагина `_BACKGROUND_BGR = (60, 60, 60)` (`plugin.py:147`); новый вход — `background_layers: [{solid: [60, 60, 60]},
  {tile: <тот же файл>}]` (серый симметричен, перестановка RGB/BGR не меняет цвет).

Таблица «старый тест -> эквивалент здесь»:
  1.1::test_background_texture_only_frames_are_byte_identical
      -> test_a3_layers_solid_plus_tile_reproduces_pre_task_texture_sha
  3.6::test_unreadable_texture_logs_once_and_falls_back -> test_a4_unreadable_tile_...[missing]
  3.6hazards::test_h9_corrupt_texture_file... -> test_a4_unreadable_tile_...[corrupt]
  3.6hazards::test_h8_relative_background_texture_resolved...
      -> test_a4_relative_tile_path_is_resolved_from_repo_root_not_cwd
  3.6::test_texture_channel_order_in_frame -> входит в test_a4_relative_tile_path_... (пиксель (77, 88, 99) BGR)
  (направление/цикличность/узкий тайл плагина — новые тесты на тех же свойствах; у 3.6 они были у компоновщика)

Кадр плагина — BGR. Цвет `solid` в конфиге — RGB; файл пишется в BGR.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

# Plugins/sim/scene_source/tests/<файл> -> parents[4] == корень репозитория.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEADLINE_S = 60.0


# --------------------------------------------------------------------------------------
# Хелперы (копии паттернов тестов 1.1/3.6; сами ничего не тестируют)
# --------------------------------------------------------------------------------------


def _run_with_deadline(fn, deadline_s: float = _DEADLINE_S):
    """`fn` в daemon-потоке с join-дедлайном: зависание = падение теста, а не подвисший прогон."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        pass


def _push_creation(sp: _FakeStateProxy, value: int) -> None:
    sp.emit([Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value, "t": 0.0}, source="robot")])


def _push_value(sp: _FakeStateProxy, value: int) -> None:
    sp.emit([Delta(path="sim.belt.encoder.value", old_value=None, new_value=value, source="robot")])


def _make_preset(tmp_path: Path) -> Path:
    """Каталог из одного класса (красный диск 25x25 на прозрачном; BGR (0, 0, 255)) + YAML-пресет."""
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True, exist_ok=True)
    size = 25
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    inside = (xx - size // 2) ** 2 + (yy - size // 2) ** 2 <= (size // 2) ** 2
    sprite[inside] = (0, 0, 255, 255)
    imwrite_unicode(class_dir / "sprite.png", sprite)
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        "catalog_dir: catalog\nangle_range_deg: [0.0, 360.0]\nlayers: []\ndefect_probability: 0.0\n", encoding="utf-8"
    )
    return preset


def _cfg(tmp_path: Path, **overrides) -> dict:
    cfg = {
        "resolution_width": 160,
        "resolution_height": 120,
        "px_per_mm": 1.0,
        "belt_y_px": 60,
        "spawn_spacing_mm": [60.0, 60.0],
        "scene_length_mm": 1e9,
        "preset_path": str(_make_preset(tmp_path)),
        "seed": 7,
    }
    cfg.update(overrides)
    return cfg


def _new_ctx(cfg: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = cfg
    return ctx


def _build(cfg: dict) -> tuple[SceneSourcePlugin, _FakeStateProxy, MagicMock]:
    """configure + start; ValueError конфигурации обязан вылететь ЗДЕСЬ."""
    ctx = _new_ctx(cfg)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx.state_proxy, ctx


def _frames_sha(cfg: dict, steps: int = 6) -> str:
    """sha256 `steps` кадров плагина (энкодер 0, 500, 1000, ...) — объекты спавнятся и едут."""
    plugin, sp, _ctx = _build(cfg)
    digest = hashlib.sha256()
    _push_creation(sp, 0)
    for step in range(1, steps + 1):
        _push_value(sp, step * 500)
        digest.update(plugin.produce()[0]["frame"].tobytes())
    return digest.hexdigest()


def _write_rgb_tile(path: Path, th: int, tw: int, seed: int = 0) -> np.ndarray:
    tile = np.random.default_rng(seed).integers(0, 256, size=(th, tw, 3), dtype=np.uint8)
    imwrite_unicode(path, tile)
    return tile


def _uniform(frame: np.ndarray) -> tuple[int, int, int] | None:
    flat = frame.reshape(-1, 3)
    return tuple(int(v) for v in flat[0]) if (flat == flat[0]).all() else None


# --------------------------------------------------------------------------------------
# A2 — ключ `background_texture` -> ValueError из configure() с подсказкой `background_layers`
# --------------------------------------------------------------------------------------

_TEXTURE_VALUES = [
    pytest.param("existing_path", id="existing_file_path"),
    pytest.param("missing_path", id="missing_file_path"),
    pytest.param("", id="empty_string"),
    pytest.param(None, id="none_value_key_present"),
]


def _texture_value(tmp_path: Path, marker: object) -> object:
    if marker == "existing_path":
        texture = tmp_path / "tile.png"
        _write_rgb_tile(texture, th=10, tw=10)
        return str(texture)
    if marker == "missing_path":
        return str(tmp_path / "missing_texture.png")
    return marker


@pytest.mark.parametrize("marker", _TEXTURE_VALUES)
def test_a2_background_texture_key_raises_valueerror_naming_background_layers(tmp_path, marker):
    """A2: ключ `background_texture` в конфиге (ЛЮБОЕ значение, включая пустое и `None` при присутствующем ключе) ->
    `ValueError` из `configure()`, в тексте есть `background_layers`. Ожидание ДО прогона: КРАСНЫЙ — сегодня ключ
    читается молча (`DID NOT RAISE`)."""
    ctx = _new_ctx(_cfg(tmp_path, background_texture=_texture_value(tmp_path, marker)))
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError) as info:
        plugin.configure(ctx)
    assert "background_layers" in str(info.value), str(info.value)


@pytest.mark.parametrize("marker", ["existing_path", None], ids=["texture_path", "texture_none"])
def test_a2_background_texture_together_with_background_layers_raises_valueerror_naming_background_layers(
    tmp_path, marker
):
    """A2: `background_texture` вместе с `background_layers` — тот же `ValueError` с `background_layers` в тексте.
    Ожидание ДО прогона: путь — ЗЕЛЁНЫЙ (взаимоисключение 1.1 уже бросает ValueError и называет оба ключа);
    `None` при присутствующем ключе — КРАСНЫЙ (сегодня `None` == «ключа нет»)."""
    ctx = _new_ctx(
        _cfg(
            tmp_path,
            background_layers=[{"solid": [0, 0, 0]}],
            background_texture=_texture_value(tmp_path, marker),
        )
    )
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError) as info:
        plugin.configure(ctx)
    assert "background_layers" in str(info.value), str(info.value)


# Литералы 1.1 (Plugins/sim/scene_source/tests/test_background_layers_acceptance_1_1.py:155-156) — не пересчитываются.
_GOLDEN_NO_BACKGROUND_KEY_SHA = "be289ebfa70a8a1e1084537293e1727a5337bcc62393983eb4ac125ba31b603e"
_GOLDEN_BACKGROUND_TEXTURE_SHA = "5dc6ff14006e6e3d707de4ec30dac05289410936a896875baa64fac63627709a"


def test_a2_no_background_key_frames_stay_byte_identical(tmp_path):
    """A2 («без ключа — поведение 1.1 как есть»): конфиг без фоновых ключей даёт кадры с прежним sha256.
    Ожидание ДО прогона: ЗЕЛЁНЫЙ (страховочная сеть)."""
    assert _frames_sha(_cfg(tmp_path)) == _GOLDEN_NO_BACKGROUND_KEY_SHA


# --------------------------------------------------------------------------------------
# A3 — эталон старого пути держится на `background_layers`
# --------------------------------------------------------------------------------------


def test_a3_layers_solid_plus_tile_reproduces_pre_task_texture_sha(tmp_path):
    """A3: `background_layers: [{solid: [60, 60, 60]}, {tile: <файл th=40, tw=23, seed 0>}]` даёт кадры с ТЕМ ЖЕ sha256,
    что старый `background_texture` (1.1:156). Ожидание ДО прогона: ЗЕЛЁНЫЙ — путь слоёв байт-в-байт эквивалентен
    старому (проверено на уровне компоновщика тестами 1.1)."""
    texture = tmp_path / "tile.png"
    _write_rgb_tile(texture, th=40, tw=23)
    cfg = _cfg(tmp_path, background_layers=[{"solid": [60, 60, 60]}, {"tile": str(texture)}])
    assert _frames_sha(cfg) == _GOLDEN_BACKGROUND_TEXTURE_SHA


# --------------------------------------------------------------------------------------
# A4 — свойства 3.6/5.3b на пути `background_layers` (все ЗЕЛЁНЫЕ ДО прогона)
# --------------------------------------------------------------------------------------

_ROW_OUTSIDE_DISKS = 5  # диски радиуса 12 на belt_y_px=60 занимают строки ~48..72 — строка 5 чистый фон
_MARKER_COL = 100


def _marker_tile(path: Path, tw: int = 200, th: int = 120) -> None:
    """BGR-тайл (60, 60, 60) с одной колонкой `tw // 2`, у которой G = 255."""
    tile = np.full((th, tw, 3), 60, dtype=np.uint8)
    tile[:, tw // 2, 1] = 255
    imwrite_unicode(path, tile)


def _marker_cols(frame: np.ndarray) -> list[int]:
    return [int(c) for c in np.nonzero(frame[_ROW_OUTSIDE_DISKS, :, 1] == 255)[0]]


@pytest.mark.parametrize(
    ("belt_direction", "expected_cols"),
    [pytest.param(1, [172, 372], id="forward"), pytest.param(-1, [28, 228], id="reversed")],
)
def test_a4_tile_moves_with_encoder_in_the_belt_direction(tmp_path, belt_direction, expected_cols):
    """A4: энкодер 0 -> 500 (500 * 0.144473 = 72.2365 мм -> сдвиг 72 px при `px_per_mm=1`): отмеченная колонка тайла
    (шириной 200, колонка 100) стоит на 100/300, после сдвига — на `100 + belt_direction * 72` (mod 200):
    172/372 вперёд, 28/228 при `belt_direction=-1` (фон едет в ту же сторону, что объекты, и при реверсе ленты)."""
    texture = tmp_path / "marker.png"
    _marker_tile(texture)
    cfg = _cfg(
        tmp_path,
        resolution_width=400,
        belt_direction=belt_direction,
        background_layers=[{"tile": str(texture)}],
    )
    plugin, sp, _ctx = _build(cfg)
    _push_creation(sp, 0)
    assert _marker_cols(plugin.produce()[0]["frame"]) == [100, 300]
    _push_value(sp, 500)
    assert _marker_cols(plugin.produce()[0]["frame"]) == expected_cols


def test_a4_tile_shift_is_cyclic_by_tile_width(tmp_path):
    """A4: сдвиг на ровно ширину тайла (энкодер 1384 -> 1384 * 0.144473 = 199.95 -> 200 px = 5 * 40) даёт ту же строку
    кадра, что энкодер 0; а промежуточный сдвиг (энкодер 500 -> 72 px, 72 mod 40 = 32) — другую (антивакуум)."""
    texture = tmp_path / "tile40.png"
    _write_rgb_tile(texture, th=120, tw=40, seed=1)
    cfg = _cfg(tmp_path, background_layers=[{"tile": str(texture)}])
    plugin, sp, _ctx = _build(cfg)
    _push_creation(sp, 0)
    row0 = plugin.produce()[0]["frame"][_ROW_OUTSIDE_DISKS].copy()
    _push_value(sp, 500)
    row_mid = plugin.produce()[0]["frame"][_ROW_OUTSIDE_DISKS].copy()
    _push_value(sp, 1384)
    row_full = plugin.produce()[0]["frame"][_ROW_OUTSIDE_DISKS].copy()
    assert not np.array_equal(row0, row_mid), "фон не сдвинулся на 500 — тест вырожден"
    assert np.array_equal(row0, row_full)


def test_a4_narrow_tile_fills_frame_by_repetition_without_stretch(tmp_path):
    """A4: тайл шириной 23 в кадре 160: на энкодере 0 каждый столбец строки равен `u mod 23` (индекс закодирован в
    канале B файла) — повторение, не растяжение."""
    tw = 23
    tile = np.zeros((120, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u
    texture = tmp_path / "narrow.png"
    imwrite_unicode(texture, tile)
    plugin, sp, _ctx = _build(_cfg(tmp_path, background_layers=[{"tile": str(texture)}]))
    _push_creation(sp, 0)
    row = plugin.produce()[0]["frame"][_ROW_OUTSIDE_DISKS]
    assert row[:, 0].tolist() == [u % tw for u in range(160)]


def test_a4_relative_tile_path_is_resolved_from_repo_root_not_cwd(tmp_path, monkeypatch, repo_texture_dir):
    """Порт 3.6 H8 (+ порядок каналов из 3.6): относительный `tile` резолвится от корня репозитория, а не от CWD.
    CWD уводится глубже корня репо, чтобы наивное CWD-резолвление промахивалось (precondition ниже). Однородный
    BGR-тайл (77, 88, 99) -> тот же пиксель в BGR-кадре, `log_error` не вызывался."""
    texture_path = repo_texture_dir / "h8_tile.png"  # на одном диске с корнем репо (relpath C:/D: невозможен)
    imwrite_unicode(texture_path, np.full((48, 48, 3), fill_value=(77, 88, 99), dtype=np.uint8))
    relative_path = os.path.relpath(texture_path, _REPO_ROOT)

    deep = tmp_path.joinpath(*(["d"] * (len(_REPO_ROOT.parts) + 2)))
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert not (Path.cwd() / relative_path).resolve().exists(), "тест вырожден: CWD-резолвление тоже находит файл"

    cfg = _cfg(
        tmp_path,
        resolution_width=48,
        resolution_height=48,
        belt_y_px=24,
        background_layers=[{"solid": [0, 0, 0]}, {"tile": relative_path}],
    )
    plugin, _sp, ctx = _build(cfg)
    assert ctx.log_error.call_count == 0, "путь от корня репо должен читаться без ошибок"
    frame = plugin.produce()[0]["frame"]
    assert tuple(int(v) for v in frame[10, 10]) == (77, 88, 99)


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_a4_unreadable_tile_logs_one_error_layer_dropped_engine_keeps_spawning(tmp_path, kind):
    """Порт 3.6 criterion 4 + H9: нет файла / битые байты -> ровно один `log_error` из `configure()`, 0 из `produce()`,
    слой выброшен (остаётся `solid`), объекты продолжают спавниться (красный диск BGR (0, 0, 255) виден в кадрах)."""
    tile_path = tmp_path / "unreadable_tile.png"
    if kind == "corrupt":
        tile_path.write_bytes(b"not a real png \x00\x01\x02")
    cfg = _cfg(tmp_path, background_layers=[{"solid": [10, 20, 30]}, {"tile": str(tile_path)}])
    plugin, sp, ctx = _build(cfg)
    assert ctx.log_error.call_count == 1, f"ожидался ровно 1 log_error, вызовов: {ctx.log_error.call_count}"
    assert _uniform(plugin.produce()[0]["frame"]) == (30, 20, 10), "слой не выброшен или solid не рисуется"

    def frames_with_objects():
        _push_creation(sp, 0)
        frames = []
        for step in range(1, 11):
            _push_value(sp, step * 300)
            frames.append(plugin.produce()[0]["frame"])
        return frames

    frames = _run_with_deadline(frames_with_objects)
    assert all(f.shape == (120, 160, 3) for f in frames)
    assert any((f == np.array([0, 0, 255], dtype=np.uint8)).all(axis=2).any() for f in frames), "объекты не спавнятся"
    assert ctx.log_error.call_count == 1, "produce() не должен добавлять log_error по причине тайла"


# --------------------------------------------------------------------------------------
# A5 — стенд `apps/line_sim/pipeline.yaml`
# --------------------------------------------------------------------------------------


def _scene_source_entries(node: object) -> list[dict]:
    """Все словари с `plugin_name == "scene_source"` в произвольно вложенной структуре YAML."""
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("plugin_name") == "scene_source":
            found.append(node)
        for value in node.values():
            found.extend(_scene_source_entries(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_scene_source_entries(item))
    return found


def test_a5_stand_pipeline_uses_black_plus_belt_tile_layers_and_no_background_texture():
    """A5: у `scene_source` в `apps/line_sim/pipeline.yaml` ключ `background_layers` РОВНО
    `[{solid: [0, 0, 0]}, {tile: data/line_sim/belt_tile.png}]`, ключа `background_texture` нет.
    Ожидание ДО прогона: КРАСНЫЙ — сегодня `background_texture: data/line_sim/belt_tile.png`, слоёв нет."""
    data = yaml.safe_load((_REPO_ROOT / "apps" / "line_sim" / "pipeline.yaml").read_text(encoding="utf-8"))
    entries = _scene_source_entries(data)
    assert len(entries) == 1, f"ожидался один scene_source в pipeline.yaml, найдено {len(entries)}"
    entry = entries[0]
    assert "background_texture" not in entry
    assert entry.get("background_layers") == [{"solid": [0, 0, 0]}, {"tile": "data/line_sim/belt_tile.png"}]


# --------------------------------------------------------------------------------------
# A6 — старые имена не живут в коде и документации
# --------------------------------------------------------------------------------------

_OLD_NAMES = re.compile(r"background_texture|background_tile")
_SCAN_ROOTS = ("Services", "Plugins", "apps")
_SKIP_DIR_NAMES = {"tests", "__pycache__", ".git", ".venv", "node_modules", ".pytest_cache"}
_PLUGIN_PY = "Plugins/sim/scene_source/plugin.py"
_PLUGIN_PY_MAX_MATCH_LINES = 3  # проверка наличия ключа + текст ValueError (возможно в 2 строки) — запас на одну


def _old_name_hits() -> tuple[set[str], list[tuple[str, int, str]]]:
    """(множество просмотренных файлов, [(относительный путь, номер строки, текст строки)]) — все вхождения старых имён
    в `Services`, `Plugins`, `apps`, КРОМЕ каталогов `tests` на любой глубине и файлов `DECISIONS.md`."""
    scanned: set[str] = set()
    hits: list[tuple[str, int, str]] = []
    for root in _SCAN_ROOTS:
        for dirpath, dirnames, filenames in os.walk(_REPO_ROOT / root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for name in filenames:
                if name == "DECISIONS.md":
                    continue
                path = Path(dirpath) / name
                raw = path.read_bytes()
                if b"\x00" in raw:  # бинарный файл
                    continue
                rel = path.relative_to(_REPO_ROOT).as_posix()
                scanned.add(rel)
                for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
                    if _OLD_NAMES.search(line):
                        hits.append((rel, number, line.strip()))
    return scanned, hits


def test_a6_old_names_survive_only_in_the_valueerror_text_and_one_readme_migration_line():
    """A6: `background_texture` / `background_tile` вне каталогов `tests` и файлов `DECISIONS.md` разрешены ТОЛЬКО:
      (1) в `Plugins/sim/scene_source/plugin.py` — проверка ключа и текст `ValueError`: не более 3 строк, только имя
          `background_texture` (имя `background_tile`/`_load_background_tile` там запрещено);
      (2) в `README.md` — не более одной строки на файл, и эта строка называет `background_layers` (строка миграции).
    Всё остальное (код, YAML, STATUS.md, комментарии) — 0. Правило буквальное по плану («вне tests/, DECISIONS.md и
    текста ValueError/строки миграции в README»). Ожидание ДО прогона: КРАСНЫЙ — десятки вхождений."""
    scanned, hits = _old_name_hits()
    assert len(scanned) > 100, f"просмотрено подозрительно мало файлов ({len(scanned)}) — обход сломан"

    violations: list[str] = []
    plugin_py_hits = [h for h in hits if h[0] == _PLUGIN_PY]
    if len(plugin_py_hits) > _PLUGIN_PY_MAX_MATCH_LINES:
        violations.append(f"{_PLUGIN_PY}: {len(plugin_py_hits)} строк с именами (макс. {_PLUGIN_PY_MAX_MATCH_LINES})")
    for rel, number, line in plugin_py_hits:
        if "background_tile" in line:
            violations.append(f"{rel}:{number}: имя background_tile в plugin.py: {line[:120]}")

    readme_hits: dict[str, list[tuple[int, str]]] = {}
    for rel, number, line in hits:
        if rel == _PLUGIN_PY:
            continue
        if rel.endswith("/README.md"):
            readme_hits.setdefault(rel, []).append((number, line))
        else:
            violations.append(f"{rel}:{number}: {line[:120]}")
    for rel, lines in readme_hits.items():
        if len(lines) > 1:
            violations.append(f"{rel}: {len(lines)} строк с именами (допустима одна строка миграции)")
        elif "background_layers" not in lines[0][1]:
            violations.append(f"{rel}:{lines[0][0]}: миграция не называет background_layers: {lines[0][1][:100]}")

    assert not violations, f"{len(violations)} нарушений:\n" + "\n".join(violations)


def test_a6_scan_actually_sees_the_files_it_is_supposed_to_police():
    """Якорь против вырожденного A6: обход видит `plugin.py` плагина и `pipeline.yaml` стенда (иначе «0 вхождений» —
    пустота). Ожидание ДО прогона: ЗЕЛЁНЫЙ."""
    scanned, _hits = _old_name_hits()
    for rel in (_PLUGIN_PY, "apps/line_sim/pipeline.yaml", "Services/line_sim/core/scene_compositor.py"):
        assert rel in scanned, f"обход не видит {rel}"
    assert len(scanned) > 100
