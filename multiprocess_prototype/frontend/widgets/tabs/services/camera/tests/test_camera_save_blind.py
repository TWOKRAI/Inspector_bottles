# -*- coding: utf-8 -*-
"""Приёмка Task 1.10 (C-30), слепые тесты: «Camera Save через SetPluginConfig».

Камера больше не правит сырой dict рецепта. ``CameraSettingsPresenter.save()`` отправляет в редактор команды
``SetPluginConfig`` (``commands.dispatch``), затем вызывает ``save_active`` (в приложении это
``frontend.app._save_active_topology``: тот же путь, что Pipeline-Save). Файл рецепта меняется минимальной дельтой.

Цепочка настоящая: ``CameraSettingsPresenter`` -> ``CommandDispatcherOrchestrator`` (``Project.apply``) ->
``FakeTopologyRepository`` -> ``_save_active_topology`` -> ``save_editor_topology_to_recipe`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` + ``InspectorRecipeFormatHook`` -> файл в ``tmp_path``.
Фикстура A — ``recipes/tests/fixtures/letter_robot_sim_pre_c30.yaml``; в ней плагин ``camera_service`` стоит
в процессе ``camera_0`` на индексе 0. Ожидаемые значения — литералы (строки диффа, байты, тексты статусов).

Модуль же отдаёт обвязку (``make_rig`` и др.) тесту проводки секции ``test_camera_wiring.py``.
"""

from __future__ import annotations

import difflib
import functools
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

_FIXTURE_A = Path(__file__).resolve().parents[6] / "recipes" / "tests" / "fixtures" / "letter_robot_sim_pre_c30.yaml"
SLUG = "letter_robot_sim"
OLD_MTIME_NS = 1_700_000_000_000_000_000
CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"

_CAMERA_ANCHOR = "          category: source\n          config:\n            camera_type: stream\n"
_CAMERA_FLAT = "          fps: 25\n          mjpg: true\n          params:\n            brightness: 128\n"


# ---------------------------------------------------------------------------
# Обвязка (импортируется тестом проводки секции)
# ---------------------------------------------------------------------------


class FakeEngine:
    """Минимальный движок рецептов: ``recipes_dir`` + активный slug (как в test_save_conflict_rev)."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir
        self._active_name: str | None = None

    def get_active(self) -> str | None:
        return self._active_name

    def set_active(self, name: str) -> bool:
        if not (self.recipes_dir / f"{name}.yaml").exists():
            return False
        self._active_name = name
        return True

    def deactivate(self) -> None:
        self._active_name = None

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.recipes_dir.glob("*.yaml"))

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        if not (self.recipes_dir / f"{name}.yaml").exists():
            raise FileNotFoundError(name)
        self._active_name = name
        return []


def fixture_a_lf() -> bytes:
    """LF-байты фикстуры A (checkout мог превратить её в CRLF)."""
    return _FIXTURE_A.read_bytes().replace(b"\r\n", b"\n")


def camera_recipe_bytes() -> bytes:
    """Фикстура A, у которой плагин camera_service держит ПЛОСКИЕ fps: 25 / mjpg / params.brightness: 128."""
    text = fixture_a_lf().decode("utf-8")
    assert text.count(_CAMERA_ANCHOR) == 1
    head = "          category: source\n"
    return text.replace(_CAMERA_ANCHOR, head + _CAMERA_FLAT + _CAMERA_ANCHOR[len(head) :]).encode("utf-8")


def put(directory: Path, slug: str, data: bytes) -> Path:
    path = directory / f"{slug}.yaml"
    path.write_bytes(data)
    os.utime(path, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
    return path


def build_store(recipes_dir: Path, slug: str) -> Any:
    """Настоящие RecipeManager + RecipeStoreFromManager с хуком формата Inspector."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    engine = FakeEngine(recipes_dir)
    engine.set_active(slug)
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, format_hook=InspectorRecipeFormatHook())
    return RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)


def within(seconds: float, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший лок/запись даёт явный fail, а не вечный прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"{getattr(fn, '__name__', fn)!r} не вернулся за {seconds} с")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def diff_lines(before: bytes, after: bytes) -> list[str]:
    """Строки диффа ('-...'/'+...') без заголовков и @@, построчно."""
    a = before.decode("utf-8").splitlines()
    b = after.decode("utf-8").splitlines()
    out = list(difflib.unified_diff(a, b, lineterm="", n=0))
    return [line for line in out if not line.startswith("@@")][2:]


def blueprint_of(data: bytes) -> dict:
    """Секция ``blueprint`` рецепта-файла (то, из чего редактор строит модель)."""
    return yaml.safe_load(data.decode("utf-8"))["blueprint"]


def plugin_def(data: bytes, process: str, plugin: str = "camera_service") -> dict:
    """Определение плагина ``plugin`` процесса ``process`` в файле (pdef, как его видит backend)."""
    proc = next(p for p in blueprint_of(data)["processes"] if p["process_name"] == process)
    return next(p for p in proc["plugins"] if p["plugin_name"] == plugin)


def backend_config(data: bytes, process: str = "camera_0") -> dict:
    """Конфиг камеры так, как его читает backend: ``PluginOrchestrator._extract_plugin_config(pdef)``."""
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator

    return PluginOrchestrator._extract_plugin_config(plugin_def(data, process))


class FakeBridge:
    """Live-мост камеры: запоминает команды, возвращает заданный результат."""

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def on_action_command(self, plugin: str, command: str, args: dict) -> bool:
        self.calls.append((plugin, command, args))
        return self.result


class RecordingDispatcher:
    """Настоящий ``CommandDispatcherOrchestrator`` + журнал отправленных команд."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.dispatched: list[Any] = []

    def dispatch(self, command: Any, **kwargs: Any) -> Any:
        self.dispatched.append(command)
        return self._inner.dispatch(command, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def set_plugin_configs(self) -> list[tuple[str, int, str]]:
        """(process_name, plugin_index, field) каждой отправленной SetPluginConfig, по порядку."""
        from multiprocess_prototype.domain.commands import SetPluginConfig

        return [(c.process_name, c.plugin_index, c.field) for c in self.dispatched if isinstance(c, SetPluginConfig)]


class CountingCall:
    """Обёртка над ``save_active``: считает вызовы, пробрасывает результат и исключения."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self._inner()


@dataclass
class Rig:
    """Настоящая цепочка на tmp-копии рецепта: файл, стор, сессия редактора, модель, диспетчер, save_active."""

    path: Path
    src: bytes
    store: Any
    session: Any
    repo: Any
    commands: RecordingDispatcher
    save_active: CountingCall

    def pipeline_save(self) -> str:
        """Pipeline-Save: тот же вызов helper'а, что у вкладки Pipeline (без QMessageBox)."""
        from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

        return save_editor_topology_to_recipe(
            self.store,
            SLUG,
            self.repo.load().to_dict(),
            expected_rev=self.session.base_rev_for(SLUG),
            foundation=self.session.foundation_names,
        )


def make_rig(
    tmp_path: Path,
    file_bytes: bytes | None = None,
    *,
    blueprint: dict | None = None,
    foundation: tuple[str, ...] = (),
) -> Rig:
    """Собрать цепочку. Модель редактора = ``blueprint`` либо блок blueprint самого файла."""
    from multiprocess_prototype.adapters.dispatch.command_dispatcher import CommandDispatcherOrchestrator
    from multiprocess_prototype.adapters.dispatch.project_holder import ProjectHolder
    from multiprocess_prototype.domain import TopologySession
    from multiprocess_prototype.domain.entities import Topology
    from multiprocess_prototype.domain.entities.project import ApplyContext, Project
    from multiprocess_prototype.domain.tests._fakes import FakeEventBus, FakeTopologyRepository
    from multiprocess_prototype.frontend.app import _save_active_topology

    src = fixture_a_lf() if file_bytes is None else file_bytes
    path = put(tmp_path, SLUG, src)
    store = build_store(tmp_path, SLUG)
    session = TopologySession()
    session.capture_base(SLUG, store.read_raw_with_rev(SLUG)[1])
    if foundation:
        session.capture_foundation(foundation)
    topology = Topology.from_dict(blueprint if blueprint is not None else blueprint_of(src))
    repo = FakeTopologyRepository(topology)
    holder = ProjectHolder(Project.from_topology(topology))
    inner = CommandDispatcherOrchestrator(holder, repo, FakeEventBus(), lambda: ApplyContext())
    return Rig(
        path=path,
        src=src,
        store=store,
        session=session,
        repo=repo,
        commands=RecordingDispatcher(inner),
        save_active=CountingCall(functools.partial(_save_active_topology, session, store, repo)),
    )


def make_presenter(rig: Rig, *, bridge: Any = None, save_active: Any = None) -> Any:
    from multiprocess_prototype.frontend.widgets.tabs.services.camera.presenter import CameraSettingsPresenter

    return CameraSettingsPresenter(
        bridge=bridge,
        topology=rig.repo,
        recipes=rig.store,
        commands=rig.commands,
        save_active=rig.save_active if save_active is None else save_active,
    )


def _hand_edited(src: bytes) -> bytes:
    """Рецепт после правки руками: порт 5021 -> 5099 (одна строка)."""
    edited = src.replace(b"      port: 5021\n", b"      port: 5099\n")
    assert edited != src
    return edited


# ---------------------------------------------------------------------------
# Сам стенд: проверка обвязки (не ACC)
# ---------------------------------------------------------------------------


def test_rig_records_set_plugin_config_dispatch(tmp_path: Path) -> None:
    """Достижимость для ассертов «dispatch не вызван»: журнал видит SetPluginConfig, а модель реально меняется."""
    from multiprocess_prototype.domain.commands import SetPluginConfig

    rig = make_rig(tmp_path)

    rig.commands.dispatch(SetPluginConfig(process_name="camera_0", plugin_index=0, field="fps", value=30))

    assert rig.commands.set_plugin_configs() == [("camera_0", 0, "fps")]
    camera = next(p for p in rig.repo.load().to_dict()["processes"] if p["process_name"] == "camera_0")
    assert camera["plugins"][0]["config"]["fps"] == 30


# ---------------------------------------------------------------------------
# ACC 1-2: минимальная дельта и Pipeline-Save после Camera Save
# ---------------------------------------------------------------------------


def test_acc1_camera_save_writes_minimal_delta(tmp_path: Path) -> None:
    """ACC 1: Camera Save {fps: 30, brightness: 50} -> True, дифф файла ровно три строки внутри config камеры."""
    rig = make_rig(tmp_path)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)
    presenter.apply_param("brightness", 50)

    assert within(60, presenter.save) is True

    assert diff_lines(rig.src, rig.path.read_bytes()) == [
        "+            fps: 30",
        "+            params:",
        "+              brightness: 50",
    ]


def test_acc2_pipeline_save_after_camera_save_is_noop(tmp_path: Path) -> None:
    """ACC 2: после Camera Save Pipeline-Save без правок не даёт RecipeConflict и не меняет байты."""
    rig = make_rig(tmp_path)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)
    assert within(60, presenter.save) is True
    after_camera = rig.path.read_bytes()
    assert after_camera != rig.src  # Camera Save что-то записал: «байты не меняются» ниже не вакуумно

    within(60, rig.pipeline_save)  # RecipeConflict здесь пробросился бы и завалил тест

    assert rig.path.read_bytes() == after_camera


# ---------------------------------------------------------------------------
# ACC 3: внешняя правка файла
# ---------------------------------------------------------------------------


def test_acc3_hand_edit_conflict_then_rebase_keeps_pending(tmp_path: Path) -> None:
    """ACC 3: ручная правка -> False, файл цел, last_error = текст конфликта; после новой базы save() пишет fps: 30."""
    rig = make_rig(tmp_path)
    presenter = make_presenter(rig, bridge=FakeBridge(False))  # live-мост отказал: pending всё равно копится
    presenter.apply_fps(30)
    hand_edited = _hand_edited(rig.src)
    rig.path.write_bytes(hand_edited)

    assert within(60, presenter.save) is False

    assert rig.path.read_bytes() == hand_edited
    assert presenter.last_error == CONFLICT_TEXT
    # Пользователь перезагрузил рецепт: база = rev файла. Pending не потерян -> запись проходит.
    rig.session.capture_base(SLUG, rig.store.read_raw_with_rev(SLUG)[1])
    assert within(60, presenter.save) is True
    after = rig.path.read_bytes()
    assert backend_config(after)["fps"] == 30
    assert b"      port: 5099\n" in after  # ручная правка файла не затёрта
    assert within(60, presenter.save) is False  # pending пуст
    assert presenter.last_error == ""


# ---------------------------------------------------------------------------
# ACC 4: пустой pending
# ---------------------------------------------------------------------------


def test_acc4_empty_pending_does_not_call_save_active(tmp_path: Path) -> None:
    """ACC 4: пустой pending -> False, save_active не вызван, байты и st_mtime_ns файла прежние."""
    rig = make_rig(tmp_path)
    mtime_before = rig.path.stat().st_mtime_ns
    presenter = make_presenter(rig, bridge=FakeBridge(True))

    assert within(60, presenter.save) is False

    assert rig.save_active.calls == 0
    assert rig.path.read_bytes() == rig.src
    assert rig.path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# ACC 5, 5б, 7: что читает backend
# ---------------------------------------------------------------------------


def test_acc5_flat_fps_in_file_backend_reads_new_value(tmp_path: Path) -> None:
    """ACC 5: в файле плоский fps: 25, Camera Save fps: 30 -> backend (_extract_plugin_config) читает fps == 30."""
    src = camera_recipe_bytes()
    rig = make_rig(tmp_path, src)
    assert backend_config(src)["fps"] == 25  # исходное состояние: backend видит 25
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)

    assert within(60, presenter.save) is True

    assert backend_config(rig.path.read_bytes())["fps"] == 30


def test_acc5b_fps_inside_config_changes_one_line(tmp_path: Path) -> None:
    """ACC 5б: fps: 25 внутри config -> Camera Save fps: 30: дифф ровно «-25 / +30», backend читает 30."""
    text = fixture_a_lf().decode("utf-8")
    anchor = "            camera_type: stream\n"
    assert text.count(anchor) == 1
    src = text.replace(anchor, anchor + "            fps: 25\n").encode("utf-8")
    rig = make_rig(tmp_path, src)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)

    assert within(60, presenter.save) is True

    after = rig.path.read_bytes()
    assert diff_lines(src, after) == ["-            fps: 25", "+            fps: 30"]
    assert backend_config(after)["fps"] == 30


def test_acc7_params_merge_with_existing_flat_params(tmp_path: Path) -> None:
    """ACC 7: в файле params.brightness: 128, Camera Save {contrast: 10} -> backend видит оба параметра."""
    src = camera_recipe_bytes()
    rig = make_rig(tmp_path, src)
    assert backend_config(src)["params"] == {"brightness": 128}
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_param("contrast", 10)

    assert within(60, presenter.save) is True

    assert backend_config(rig.path.read_bytes())["params"] == {"brightness": 128, "contrast": 10}


# ---------------------------------------------------------------------------
# ACC 6, 11: нечего сохранять
# ---------------------------------------------------------------------------


def test_acc6_no_camera_service_in_model(tmp_path: Path) -> None:
    """ACC 6: в модели нет camera_service -> False, ни одной команды, файл не тронут."""
    src = fixture_a_lf()
    blueprint = blueprint_of(src)
    camera = next(p for p in blueprint["processes"] if p["process_name"] == "camera_0")
    assert [p["plugin_name"] for p in camera["plugins"]] == ["camera_service"]  # убираем именно его
    camera["plugins"] = []
    rig = make_rig(tmp_path, src, blueprint=blueprint)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)

    assert within(60, presenter.save) is False

    assert rig.commands.dispatched == []
    assert rig.path.read_bytes() == src


def test_acc11_no_active_recipe(tmp_path: Path) -> None:
    """ACC 11: get_active() пуст -> False, ни одной команды SetPluginConfig, файл не тронут."""
    rig = make_rig(tmp_path)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)
    rig.store.deactivate()
    assert rig.store.get_active() is None  # предусловие: активного рецепта действительно нет

    assert within(60, presenter.save) is False

    assert rig.commands.dispatched == []
    assert rig.path.read_bytes() == rig.src


# ---------------------------------------------------------------------------
# ACC 8-10: расположение процессов и плагинов
# ---------------------------------------------------------------------------


def test_acc8_foundation_process_first_in_model(tmp_path: Path) -> None:
    """ACC 8: модель с процессом devices (фундамент) на первом месте -> дифф файла только строка fps."""
    src = fixture_a_lf()
    blueprint = blueprint_of(src)
    procs = blueprint["processes"]
    devices = next(p for p in procs if p["process_name"] == "devices")
    blueprint["processes"] = [devices] + [p for p in procs if p is not devices]
    assert procs[0]["process_name"] != "devices"  # порядок в модели действительно изменён
    assert blueprint["processes"][0]["process_name"] == "devices"
    rig = make_rig(tmp_path, src, blueprint=blueprint, foundation=("devices",))
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)

    assert within(60, presenter.save) is True

    assert diff_lines(src, rig.path.read_bytes()) == ["+            fps: 30"]


def test_acc9_two_cameras_only_camera_0_changes(tmp_path: Path) -> None:
    """ACC 9: две камеры -> команды только для camera_0, дифф как в ACC 1, config camera_1 без fps и params."""
    text = fixture_a_lf().decode("utf-8")
    start = text.index("    - process_name: camera_0\n")
    end = text.index("    - process_name: vision\n")
    block = text[start:end]
    assert block.count("process_name: camera_0\n") == 1
    src = (text[:end] + block.replace("process_name: camera_0\n", "process_name: camera_1\n") + text[end:]).encode(
        "utf-8"
    )
    rig = make_rig(tmp_path, src)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)
    presenter.apply_param("brightness", 50)

    assert within(60, presenter.save) is True

    assert rig.commands.set_plugin_configs() == [("camera_0", 0, "fps"), ("camera_0", 0, "params")]
    after = rig.path.read_bytes()
    assert diff_lines(src, after) == [
        "+            fps: 30",
        "+            params:",
        "+              brightness: 50",
    ]
    second = backend_config(after, "camera_1")
    assert second["camera_type"] == "stream"  # блок camera_1 найден и прочитан: отсутствие ключей ниже не вакуумно
    assert "fps" not in second
    assert "params" not in second


def test_acc10_camera_service_not_first_plugin(tmp_path: Path) -> None:
    """ACC 10: camera_service на индексе 1 -> одна SetPluginConfig(camera_0, 1, fps, 30), дифф только строка fps."""
    from multiprocess_prototype.domain.commands import SetPluginConfig

    text = fixture_a_lf().decode("utf-8")
    camera_start = text.index("    - process_name: camera_0\n")
    marker = "      plugins:\n"
    at = text.index(marker, camera_start) + len(marker)
    src = (text[:at] + "        - plugin_name: capture_stub\n          config: {}\n" + text[at:]).encode("utf-8")
    rig = make_rig(tmp_path, src)
    presenter = make_presenter(rig, bridge=FakeBridge(True))
    presenter.apply_fps(30)

    assert within(60, presenter.save) is True

    assert rig.commands.dispatched == [SetPluginConfig(process_name="camera_0", plugin_index=1, field="fps", value=30)]
    assert diff_lines(src, rig.path.read_bytes()) == ["+            fps: 30"]


# ---------------------------------------------------------------------------
# ACC 13: прочие ошибки save_active
# ---------------------------------------------------------------------------


class _SwitchableSave:
    """save_active, который бросает заданное исключение, пока оно задано, иначе возвращает True."""

    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return True


def _validation_error() -> Exception:
    from multiprocess_prototype.recipes.save import RecipeValidationError

    return RecipeValidationError(["x"])


@pytest.mark.parametrize(
    ("make_error", "expected_last_error"),
    [(_validation_error, "x"), (lambda: RuntimeError("другое"), "")],
    ids=["validation", "runtime"],
)
def test_acc13_other_save_errors_swallowed_pending_kept(
    tmp_path: Path, make_error: Any, expected_last_error: str
) -> None:
    """ACC 13: save_active бросил не конфликт -> save() False, не бросает, pending цел.

    last_error: RuntimeError -> пуст; RecipeValidationError -> его текст (Task 1.16 m1, правка лида 2026-11-07).
    """
    rig = make_rig(tmp_path)
    switch = _SwitchableSave(make_error())
    assert str(switch.error) != CONFLICT_TEXT
    presenter = make_presenter(rig, bridge=FakeBridge(True), save_active=switch)
    presenter.apply_fps(30)

    assert within(60, presenter.save) is False  # исключение наружу не вышло (within пробросил бы его)

    assert switch.calls == 1  # save_active достигнут: False не из-за раннего выхода
    assert presenter.last_error == expected_last_error
    switch.error = None
    assert within(60, presenter.save) is True  # True возможен только при непустом pending: он сохранился
    assert switch.calls == 2
