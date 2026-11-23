# -*- coding: utf-8 -*-
"""Task R1 — слепые acceptance-тесты команды ``scene.sequence`` плагина ``SceneSourcePlugin``.

Контракт — ТОЛЬКО раздел ACCEPTANCE (A1-A11) и REDS задачи R1 (``plans/line-sim/tasks/R1.md``);
разделы DESIGN/HAZARDS/TRAPS/FILES тестеру не показывались. Worktree на коммите до реализации:
команды ``scene.sequence`` в плагине нет по построению, все тесты ожидаемо КРАСНЫЕ — причина
«команда отсутствует в ``plugin.commands``» (проверка ``assert`` в ``_call``).

Что наблюдается (только публичная поверхность):
  * ответы команд ``scene.sequence`` / ``scene.status`` / ``scene.pause`` через ``plugin.commands``;
  * паспорта в ``sim.objects`` (``state_proxy.set("sim.objects", {...})``): ``class_name``,
    ``angle_deg``; порядок подачи = порядок первого появления ``object_id`` в публикациях.

Время: ``time.monotonic`` подменён (как в ``test_scene_controls_acceptance.py``); каждый шаг
``_Rig.step`` двигает часы на 1,5 с и энкодер вперёд, поэтому минимальный интервал между дисками
списка (A10, 1,0 с) тут не мешает: за шаг подаётся не более одного диска. Режим спавна — ``interval_s``
(первый тик только взводит срок, объект идёт на следующем шаге; тесты крутят шаги до цели с потолком).

Каталог классов — временный, во ``tmp_path`` (папки букв в NFC, RGBA PNG 16x16); ``data/`` не читается.
Буквы заданы кодовыми точками (``\\u04xx``), чтобы кириллица не смешалась с латиницей-двойником.

Догадки/неоднозначности (не угадывались в коде, а вынесены в отчёт):
  * ответ ``ok`` на первую подачу проверяется только по ``status`` (форма ``queued``/``dropped`` в
    ACCEPTANCE дана для ``replace`` — A8 — и для ``random`` — A9);
  * ``unknown`` сравнивается как список в порядке первого появления без повторов (A4: ``["Я", "Ъ"]``).
"""

from __future__ import annotations

import math
import unicodedata
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ScenePreset

# --- буквы по кодовым точкам (кириллица, NFC) ---------------------------------------------
CA = "А"  # А
CB = "Б"  # Б
CE = "Е"  # Е
CYO = "Ё"  # Ё
CR = "Р"  # Р
CYA = "Я"  # Я
CHARD = "Ъ"  # Ъ
CE_LOWER = "е"  # е (строчная)
CI_SHORT_NFC = "Й"  # Й, одна кодовая точка (NFC)
CI_SHORT_NFD = "Й"  # Й, И + combining breve (NFD)

_STEP_DT = 1.5  # сим-секунд на шаг
_ENC_STEP = 100.0  # тиков энкодера на шаг (лента едет)


# --------------------------------------------------------------------------- #
# Харнесс                                                                     #
# --------------------------------------------------------------------------- #


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


def _write_catalog(root: Path, letters: list[str]) -> Path:
    catalog = root / "cat"
    for index, letter in enumerate(letters):
        folder = catalog / letter
        folder.mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, :3] = 60 + 20 * index
        sprite[:, :, 3] = 255
        imwrite_unicode(folder / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return catalog


def _write_preset(root: Path, catalog: Path) -> Path:
    preset = ScenePreset(catalog_dir=str(catalog), angle_range_deg=(0.0, 360.0), defect_probability=0.0, layers=[])
    path = root / "preset.yaml"
    preset.to_yaml(path)
    return path


class _Rig:
    """Плагин с реальным движком, фейковым ``state_proxy`` и управляемыми часами."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, letters: list[str]) -> None:
        self.clock = [1000.0]
        self.enc = 0.0
        monkeypatch.setattr("time.monotonic", lambda: self.clock[0])
        catalog = _write_catalog(tmp_path, letters)
        preset_path = _write_preset(tmp_path, catalog)
        self.sp = _FakeStateProxy()
        ctx = MagicMock()
        ctx.state_proxy = self.sp
        ctx.config = {
            "resolution_width": 64,
            "resolution_height": 64,
            "spawn_encoder": 0,
            "px_per_mm": 1.0,
            "stale_ms": 200,
            "spawn_interval_s": [0.1, 0.1],
            "scene_length_mm": 1e9,
            "preset_path": str(preset_path),
            "seed": 0,
        }
        self.plugin = SceneSourcePlugin()
        self.plugin.configure(ctx)
        assert self.plugin._compositor is not None, f"движок не собрался (фикстура): {ctx.log_error.call_args_list}"
        self.plugin.start(ctx)
        self._push()  # мир появился: спавнер начинает тикать

    def _push(self) -> None:
        self.sp.emit(
            [
                Delta(
                    path="sim.belt.encoder",
                    old_value=object(),
                    new_value={"value": self.enc, "mm_s": 0.0, "t": self.clock[0]},
                    source="robot",
                )
            ]
        )

    def step(self, dt: float = _STEP_DT) -> None:
        self.clock[0] += dt
        self.enc += _ENC_STEP
        self._push()
        self.plugin.produce()

    def fed(self) -> list[tuple[str, float]]:
        """Подано объектов: ``(class_name, angle_deg)`` в порядке первого появления ``object_id``."""
        seen: dict[str, dict] = {}
        for path, value in self.sp.set_calls:
            if path == "sim.objects":
                for object_id, passport in value.items():  # type: ignore[union-attr]
                    seen.setdefault(object_id, dict(passport))
        return [(p["class_name"], p["angle_deg"]) for p in seen.values()]

    def step_until_fed(self, count: int, limit: int = 40) -> None:
        for _ in range(limit):
            if len(self.fed()) >= count:
                return
            self.step()
        raise AssertionError(f"за {limit} шагов подано {len(self.fed())} объектов из ожидаемых {count}: {self.fed()}")

    def call(self, name: str, data: dict | None = None) -> dict:
        commands = self.plugin.commands
        assert name in commands, f"команда {name!r} отсутствует в plugin.commands ({sorted(commands)})"
        return getattr(self.plugin, commands[name])(data)

    def sequence_status(self) -> dict:
        return self.call("scene.status")["sequence"]


def _pairs(*pairs: tuple[str, float]) -> list[list]:
    return [[letter, angle] for letter, angle in pairs]


# --------------------------------------------------------------------------- #
# A1 + A2: буквы и углы подаются в порядке списка                             #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_letters_and_angles_fed_in_list_order(tmp_path, monkeypatch):
    """A1+A2: список Р/0, А/0, Е/30 при каталоге {А, Е, Р} -> три объекта строго по порядку, углы
    ровно 0.0, 0.0, 30.0 (равенство float, не допуск); после ответа ``ok`` других классов нет.
    Ловит: случайный класс/угол вместо списка, перестановку порядка, угол из диапазона пресета."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": _pairs((CR, 0), (CA, 0), (CE, 30))})
    assert resp["status"] == "ok", resp

    rig.step_until_fed(3)
    for _ in range(5):  # лишние шаги: четвёртого объекта (и объекта другого класса) быть не должно
        rig.step()

    fed = rig.fed()
    assert fed == [(CR, 0.0), (CA, 0.0), (CE, 30.0)], fed
    assert all(isinstance(angle, float) for _letter, angle in fed), fed


@pytest.mark.timeout(60)
def test_angle_137_5_exact_twenty_times(tmp_path, monkeypatch):
    """A2 (вторая часть): пресет ``angle_range_deg [0, 360]``, список ``[["А",137.5]]x20`` -> 20 паспортов
    с ``angle_deg == 137.5`` ровно. Ловит: угол, перебитый розыгрышем из диапазона пресета."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": _pairs(*[(CA, 137.5)] * 20)})
    assert resp["status"] == "ok", resp

    rig.step_until_fed(20, limit=80)
    for _ in range(3):
        rig.step()

    fed = rig.fed()
    assert fed == [(CA, 137.5)] * 20, fed


@pytest.mark.timeout(60)
def test_negative_zero_angle_is_normalised(tmp_path, monkeypatch):
    """A5 (последняя строка): ``[["А",-0.0]]`` -> ``ok``, паспорт ``angle_deg == 0.0`` и знак ``+``
    (``math.copysign(1.0, angle_deg) == 1.0``). Ловит: ``-0.0`` в паспорте."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": [[CA, -0.0]]})
    assert resp["status"] == "ok", resp

    rig.step_until_fed(1)
    angle = rig.fed()[0][1]
    assert angle == 0.0
    assert math.copysign(1.0, angle) == 1.0


# --------------------------------------------------------------------------- #
# A4: неизвестная буква                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_unknown_letter_invalid(tmp_path, monkeypatch):
    """A4: ``[Я, А, Ъ, Я]`` при каталоге без Я и Ъ -> ``error``/``invalid``, ``unknown == ["Я", "Ъ"]``;
    ``scene.status.sequence`` после — нули в режиме ``random`` (запрос ничего не изменил).
    Ловит: частичное принятие списка, потерянный/дублированный ``unknown``, побочное состояние."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": _pairs((CYA, 0), (CA, 0), (CHARD, 10), (CYA, 5))})

    assert resp["status"] == "error", resp
    assert resp["code"] == "invalid", resp
    assert resp["unknown"] == [CYA, CHARD], resp
    assert rig.sequence_status() == {"mode": "random", "total": 0, "fed": 0, "skipped": 0, "remaining": 0}


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("letter", "catalog_letters"),
    [
        pytest.param(CE_LOWER, [CE, CA], id="lowercase_e_vs_capital"),
        pytest.param(CI_SHORT_NFD, [CI_SHORT_NFC, CA], id="NFD_Y_short_vs_NFC_folder"),
    ],
)
def test_unknown_letter_exact_comparison(tmp_path, monkeypatch, letter, catalog_letters):
    """A4 (точное сравнение): строчная ``е`` при папке ``Е`` и ``Й`` в NFD при папке ``Й`` в NFC -> ``unknown``
    со входной буквой как есть. Ловит: регистронезависимое или нормализующее сравнение букв."""
    assert unicodedata.is_normalized("NFC", catalog_letters[0])  # фикстура: папка в NFC
    rig = _Rig(tmp_path, monkeypatch, catalog_letters)
    resp = rig.call("scene.sequence", {"discs": [[letter, 0]]})

    assert resp["status"] == "error", resp
    assert resp["code"] == "invalid", resp
    assert resp["unknown"] == [letter], resp


@pytest.mark.timeout(60)
def test_yo_and_ye_are_distinct_classes(tmp_path, monkeypatch):
    """A4 (Ё/Е): каталог {Ё, Е}, список ``[["Ё",0],["Е",0]]`` -> ``ok``, паспорта ``class_name`` Ё, Е.
    Ловит: склейку Ё с Е при поиске класса."""
    rig = _Rig(tmp_path, monkeypatch, [CYO, CE])
    resp = rig.call("scene.sequence", {"discs": _pairs((CYO, 0), (CE, 0))})
    assert resp["status"] == "ok", resp

    rig.step_until_fed(2)
    assert [letter for letter, _angle in rig.fed()] == [CYO, CE]


# --------------------------------------------------------------------------- #
# A5 + A6: кривые запросы                                                     #
# --------------------------------------------------------------------------- #

_OK_PAIR = [CA, 0]
_BAD_SECOND_PAIR = [
    pytest.param([CA, 360], id="angle_360"),
    pytest.param([CA, -0.5], id="angle_minus_0_5"),
    pytest.param([CA, "30"], id="angle_str"),
    pytest.param([CA, True], id="angle_true"),
    pytest.param([CA, float("nan")], id="angle_nan"),
    pytest.param([CA, float("inf")], id="angle_inf"),
    pytest.param([CA, float("-inf")], id="angle_minus_inf"),
    pytest.param([CA, 10**400], id="angle_huge_int"),
    pytest.param([CA], id="pair_len_1"),
    pytest.param([CA, 0, 1], id="pair_len_3"),
    pytest.param([[CA], 0], id="unhashable_letter"),
    pytest.param([5, 0], id="letter_not_str"),
]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("bad_pair", _BAD_SECOND_PAIR)
def test_malformed_requests_invalid(tmp_path, monkeypatch, bad_pair):
    """A5: кривая вторая пара -> ``invalid`` с ``index == 1``, ключа ``unknown`` нет. Ловит: исключение вместо
    ответа (``OverflowError`` на ``10**400``, ``TypeError`` на нехешируемой букве), принятие ``bool``/``nan``/``inf``,
    неверный индекс."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": [list(_OK_PAIR), bad_pair]})

    assert resp["status"] == "error", resp
    assert resp["code"] == "invalid", resp
    assert resp["index"] == 1, resp
    assert "unknown" not in resp, resp


@pytest.mark.timeout(60)
def test_malformed_form_is_checked_before_letters(tmp_path, monkeypatch):
    """A5: ``[["Я",0],["А",-1]]`` при каталоге без Я -> ``index == 1`` (ошибка формы раньше проверки букв),
    ключа ``unknown`` нет. Ловит: проверку букв до проверки формы."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": [[CYA, 0], [CA, -1]]})

    assert resp["status"] == "error", resp
    assert resp["code"] == "invalid", resp
    assert resp["index"] == 1, resp
    assert "unknown" not in resp, resp


def _discs(n: int) -> list[list]:
    return [[CA, 0] for _ in range(n)]


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("payload", "message_part"),
    [
        pytest.param({"discs": []}, "пустой список дисков", id="empty_list"),
        pytest.param({}, None, id="empty_payload"),
        pytest.param({"discs": _discs(2), "random": True}, None, id="discs_and_random"),
        pytest.param({"random": True, "replace": True}, None, id="random_and_replace"),
        pytest.param({"discs": _discs(2), "x": 1}, None, id="extra_key"),
        pytest.param({"random": False}, None, id="random_false"),
        pytest.param({"discs": _discs(2), "replace": 1}, None, id="replace_not_bool"),
        pytest.param({"discs": _discs(201)}, None, id="201_discs"),
    ],
)
def test_malformed_requests_invalid_payload(tmp_path, monkeypatch, payload, message_part):
    """A6: пустой список (сообщение содержит ``пустой список дисков``), ``{}``, ``discs``+``random``,
    ``random``+``replace``, лишний ключ, ``random: false``, ``replace: 1``, 201 диск -> ``invalid``.
    Ловит: молчаливое принятие неоднозначного запроса, лимит 200 без границы."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", payload)

    assert resp["status"] == "error", resp
    assert resp["code"] == "invalid", resp
    if message_part is not None:
        assert message_part in resp["message"], resp


@pytest.mark.timeout(60)
def test_200_discs_accepted(tmp_path, monkeypatch):
    """A6 (граница 200): список ровно из 200 дисков принимается (``ok``), 201 — ``invalid`` (см. выше).
    Ловит: лимит, срезанный на 199 или меньше."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    resp = rig.call("scene.sequence", {"discs": _discs(200)})

    assert resp["status"] == "ok", resp


# --------------------------------------------------------------------------- #
# A7 / A8: занято / замена                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_busy_while_feeding(tmp_path, monkeypatch):
    """A7: список из 3, подан 1; второй ``scene.sequence`` без ``replace`` -> ``error``/``busy``,
    ``remaining == 2``; подача продолжается СТАРЫМ списком (буквы А, Е, Р по порядку).
    Ловит: тихую замену списка, неверный счёт остатка, потерю старого списка после отказа."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CB, CE, CR])
    assert rig.call("scene.sequence", {"discs": _pairs((CA, 0), (CE, 10), (CR, 20))})["status"] == "ok"
    rig.step_until_fed(1)
    assert len(rig.fed()) == 1

    resp = rig.call("scene.sequence", {"discs": _pairs((CB, 5))})

    assert resp["status"] == "error", resp
    assert resp["code"] == "busy", resp
    assert resp["remaining"] == 2, resp
    rig.step_until_fed(3)
    for _ in range(3):
        rig.step()
    assert rig.fed() == [(CA, 0.0), (CE, 10.0), (CR, 20.0)], rig.fed()


@pytest.mark.timeout(60)
def test_replace_drops_remaining(tmp_path, monkeypatch):
    """A8: тот же случай с ``"replace": true`` -> ``ok``, ``queued == 2`` (новый), ``dropped == 2``; следующие
    объекты — буквы нового списка (Б/10, Б/20), ни одной буквы из выброшенного остатка (Е, Р).
    Ловит: дописывание в хвост вместо замены, неверный ``dropped``, подачу остатка старого списка."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CB, CE, CR])
    assert rig.call("scene.sequence", {"discs": _pairs((CA, 0), (CE, 10), (CR, 20))})["status"] == "ok"
    rig.step_until_fed(1)
    assert len(rig.fed()) == 1

    resp = rig.call("scene.sequence", {"discs": _pairs((CB, 10), (CB, 20)), "replace": True})

    assert resp["status"] == "ok", resp
    assert resp["queued"] == 2, resp
    assert resp["dropped"] == 2, resp
    rig.step_until_fed(3)
    for _ in range(5):  # хвост выброшенного списка не должен всплыть
        rig.step()
    assert rig.fed() == [(CA, 0.0), (CB, 10.0), (CB, 20.0)], rig.fed()


# --------------------------------------------------------------------------- #
# A9: исчерпание списка                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_exhausted_list_stops_spawn(tmp_path, monkeypatch):
    """A9: после исчерпания ``sequence`` = ``{mode: list, total: 3, fed: 3, skipped: 0, remaining: 0}``;
    за 30 с сим-времени при едущей ленте новых объектов нет; ``{"random": true}`` -> ``ok``,
    ``mode == "random"``, ``dropped == 0``, статус — нули в ``random``, и объекты снова появляются.
    Ловит: возврат к случайному спавну после списка, неверные счётчики, невозможность вернуться в ``random``."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    assert rig.call("scene.sequence", {"discs": _pairs((CA, 0), (CE, 10), (CR, 20))})["status"] == "ok"
    rig.step_until_fed(3)
    rig.step()  # шаг после третьего: список исчерпан
    assert rig.sequence_status() == {"mode": "list", "total": 3, "fed": 3, "skipped": 0, "remaining": 0}

    elapsed = 0.0
    while elapsed < 30.0:  # 30 сим-секунд при едущей ленте
        rig.step()
        elapsed += _STEP_DT
    assert len(rig.fed()) == 3, rig.fed()

    resp = rig.call("scene.sequence", {"random": True})
    assert resp["status"] == "ok", resp
    assert resp["mode"] == "random", resp
    assert resp["dropped"] == 0, resp
    assert rig.sequence_status() == {"mode": "random", "total": 0, "fed": 0, "skipped": 0, "remaining": 0}

    rig.step_until_fed(4, limit=20)  # объекты снова появляются
    assert len(rig.fed()) >= 4


# --------------------------------------------------------------------------- #
# A11: пауза держит позицию в списке                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_pause_holds_list_position(tmp_path, monkeypatch):
    """A11: ``scene.pause {"paused": true}`` в середине списка (подан 1 из 4) -> новых объектов нет,
    ``remaining`` не меняется (3); снятие паузы -> подача продолжается со СЛЕДУЮЩЕЙ буквы списка (Е).
    Ловит: расход списка во время паузы, потерю позиции, подачу не по порядку после паузы."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CB, CE, CR])
    assert rig.call("scene.sequence", {"discs": _pairs((CA, 0), (CE, 10), (CR, 20), (CB, 30))})["status"] == "ok"
    rig.step_until_fed(1)
    remaining_before = rig.sequence_status()["remaining"]
    assert remaining_before == 3

    assert rig.call("scene.pause", {"paused": True}) == {"status": "ok"}
    for _ in range(10):  # 15 сим-секунд на паузе
        rig.step()
    assert len(rig.fed()) == 1, rig.fed()
    assert rig.sequence_status()["remaining"] == 3

    assert rig.call("scene.pause", {"paused": False}) == {"status": "ok"}
    rig.step_until_fed(4)
    assert rig.fed() == [(CA, 0.0), (CE, 10.0), (CR, 20.0), (CB, 30.0)], rig.fed()
