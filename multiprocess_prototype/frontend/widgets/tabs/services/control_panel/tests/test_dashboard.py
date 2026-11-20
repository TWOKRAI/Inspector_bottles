"""Тесты дашборда пульта (Phase 5): роутинг presenter по source, каталог, билдеры спеки."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
)
from shiboken6 import isValid

from multiprocess_prototype.domain.commands import SetPluginConfig
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.catalog import (
    FieldRef,
    NodeCatalog,
    NodeRef,
    control_type_for_field,
    make_action_spec,
    make_param_spec,
)
from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.presenter import (
    ControlPanelPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.section import (
    build_control_panel_section,
)


class _RecBridge:
    """bridge — запись on_action_command (топология теперь приходит из services.topology)."""

    def __init__(self) -> None:
        self.actions: list[tuple[str, str, dict]] = []

    def on_action_command(self, plugin: str, command: str, args: dict) -> bool:
        self.actions.append((plugin, command, args))
        return True


class _RecCommands:
    def __init__(self) -> None:
        self.dispatched: list = []

    def dispatch(self, cmd, **kw) -> None:
        self.dispatched.append(cmd)


class _FakeTopoModel:
    def __init__(self, data: dict) -> None:
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class _FakeTopoRepo:
    """TopologyRepository-заглушка: load().to_dict() → заданный dict."""

    def __init__(self, data: dict) -> None:
        self._model = _FakeTopoModel(data)

    def load(self) -> _FakeTopoModel:
        return self._model


class _RecServices:
    def __init__(self, topology: dict | None = None) -> None:
        self.commands = _RecCommands()
        self.topology = _FakeTopoRepo(topology or {})


# --------------------------------------------------------------------------- #
# Билдеры спеки (чистый Python)
# --------------------------------------------------------------------------- #


def test_make_param_spec_angle() -> None:
    node = NodeRef("points", 0, "robot_scale", "processing")
    field = FieldRef("x0", "Угол ЛВ X (мм)", float, -2000.0, 2000.0, False)
    spec = make_param_spec(node, field)
    assert spec["source"] == "param"
    assert spec["target_process"] == "points"
    assert spec["target_plugin_index"] == 0
    assert spec["target_field"] == "x0"
    assert spec["type"] == "number"  # numeric → number по умолчанию
    assert spec["min"] == -2000.0 and spec["max"] == 2000.0


def test_make_action_spec_speed_with_value() -> None:
    node = NodeRef("devices", 0, "device_hub", "hub")
    spec = make_action_spec(
        node,
        "robot_draw_set_speed",
        ctype="slider",
        value_arg="pct",
        command_args={"device_id": "robot_main"},
        vmin=1,
        vmax=100,
    )
    assert spec["source"] == "action"
    assert spec["target_command"] == "robot_draw_set_speed"
    assert spec["value_arg"] == "pct"
    assert spec["command_args"] == {"device_id": "robot_main"}
    assert spec["min"] == 1.0 and spec["max"] == 100.0


def test_make_param_spec_carries_value() -> None:
    node = NodeRef("points", 0, "robot_scale", "processing")
    field = FieldRef("y0", "Угол ЛВ Y (мм)", float, -2000.0, 2000.0, False, default=0.0)
    spec = make_param_spec(node, field, value=144.0)
    assert spec["value"] == 144.0  # стартовое значение «которое было», не min


def test_make_action_spec_button_is_pure_trigger() -> None:
    node = NodeRef("devices", 0, "device_hub", "hub")
    spec = make_action_spec(node, "robot_home")
    assert spec["type"] == "button"
    assert spec["value_arg"] == ""
    assert "min" not in spec  # у кнопки нет диапазона


def test_control_type_for_field() -> None:
    assert control_type_for_field(FieldRef("b", "", bool, None, None, False)) == "toggle"
    assert control_type_for_field(FieldRef("n", "", float, 0, 1, False)) == "number"
    assert control_type_for_field(FieldRef("n", "", float, 0, 1, False), numeric_as="slider") == "slider"
    assert control_type_for_field(FieldRef("s", "", str, None, None, False)) == "text"


# --------------------------------------------------------------------------- #
# Роутинг presenter по source
# --------------------------------------------------------------------------- #


def test_operate_param_dispatches_live_field_write() -> None:
    services = _RecServices()
    p = ControlPanelPresenter(bridge=_RecBridge(), services=services)
    spec = {
        "id": "param_robot_scale_x0",
        "source": "param",
        "target_process": "points",
        "target_plugin_index": 0,
        "target_field": "x0",
        "type": "number",
    }
    assert p.operate(spec, 12.5) is True
    cmd = services.commands.dispatched[0]
    assert isinstance(cmd, SetPluginConfig)
    assert (cmd.process_name, cmd.plugin_index, cmd.field, cmd.value) == ("points", 0, "x0", 12.5)


def test_operate_action_resolves_plugin_and_passes_value() -> None:
    topo = {"processes": [{"process_name": "devices", "plugins": [{"plugin_name": "device_hub"}]}]}
    bridge = _RecBridge()
    p = ControlPanelPresenter(bridge=bridge, services=_RecServices(topo))
    spec = {
        "id": "spd",
        "source": "action",
        "target_process": "devices",
        "target_plugin_index": 0,
        "target_command": "robot_draw_set_speed",
        "value_arg": "pct",
        "command_args": {"device_id": "robot_main"},
        "type": "slider",
        "min": 1,
        "max": 100,
    }
    assert p.operate(spec, 55.0) is True
    assert bridge.actions == [("device_hub", "robot_draw_set_speed", {"device_id": "robot_main", "pct": 55.0})]


def test_operate_action_button_pure_trigger() -> None:
    topo = {"processes": [{"process_name": "devices", "plugins": [{"plugin_name": "device_hub"}]}]}
    bridge = _RecBridge()
    p = ControlPanelPresenter(bridge=bridge, services=_RecServices(topo))
    spec = {
        "id": "home",
        "source": "action",
        "target_process": "devices",
        "target_plugin_index": 0,
        "target_command": "robot_home",
        "type": "button",
    }
    assert p.operate(spec, True) is True
    assert bridge.actions == [("device_hub", "robot_home", {})]


def test_operate_monitor_is_readonly_noop() -> None:
    bridge = _RecBridge()
    p = ControlPanelPresenter(bridge=bridge, services=_RecServices())
    spec = {"id": "m", "source": "monitor", "target_process": "points", "target_field": "points_last"}
    assert p.operate(spec, 5) is False
    assert bridge.actions == []


def test_operate_param_missing_target_is_safe() -> None:
    p = ControlPanelPresenter(bridge=_RecBridge(), services=_RecServices())
    assert p.operate({"id": "x", "source": "param"}, 1) is False


def test_operate_action_unresolved_plugin_is_safe() -> None:
    # target_process нет в топологии → плагин не резолвится → False, без падения.
    bridge = _RecBridge()
    p = ControlPanelPresenter(bridge=bridge, services=_RecServices({"processes": []}))
    spec = {"id": "a", "source": "action", "target_process": "ghost", "target_command": "x"}
    assert p.operate(spec, True) is False
    assert bridge.actions == []


# --------------------------------------------------------------------------- #
# NodeCatalog
# --------------------------------------------------------------------------- #


def test_catalog_nodes_from_topology() -> None:
    topo = {
        "processes": [
            {"process_name": "a", "plugins": [{"plugin_name": "p1", "category": "source"}, {"plugin_name": "p2"}]},
            {"process_name": "b", "plugins": []},
        ]
    }
    cat = NodeCatalog(topo)
    nodes = cat.nodes()
    assert [(n.process_name, n.plugin_index, n.plugin_name) for n in nodes] == [("a", 0, "p1"), ("a", 1, "p2")]
    assert nodes[0].label == "a.p1  (source)"


def test_catalog_unknown_plugin_empty() -> None:
    cat = NodeCatalog({})
    assert cat.fields("does_not_exist") == []
    assert cat.commands("does_not_exist") == []


def test_catalog_field_value_from_config() -> None:
    topo = {
        "processes": [
            {"process_name": "points", "plugins": [{"plugin_name": "robot_scale", "config": {"x0": 0.0, "y0": 144.0}}]}
        ]
    }
    cat = NodeCatalog(topo)
    node = NodeRef("points", 0, "robot_scale", "processing")
    assert cat.field_value(node, "y0", -1) == 144.0  # значение из рецепта
    assert cat.field_value(node, "x1", -1) == -1  # нет override → fallback


def _find_root() -> pathlib.Path:
    # Якорь по уникальным именам топ-пакетов (Windows FS case-insensitive — нельзя
    # ориентироваться на «Plugins»/«Services»: совпадут с widgets/.../services).
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "multiprocess_framework").is_dir() and (parent / "multiprocess_prototype").is_dir():
            return parent
    raise RuntimeError("корень проекта не найден")


@pytest.fixture(scope="module")
def _discovered() -> None:
    """Наполнить PluginRegistry реальными плагинами (для fields/commands)."""
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    root = _find_root()
    PluginRegistry.discover(str(root / "Plugins"), str(root / "Services"))


def test_catalog_fields_robot_scale(_discovered: None) -> None:
    cat = NodeCatalog({})
    names = {f.name for f in cat.fields("robot_scale")}
    assert {"x0", "y0", "x1", "y1"} <= names
    assert "points_last" not in names  # readonly отфильтрован
    assert "points_last" in {f.name for f in cat.fields("robot_scale", editable_only=False)}
    x0 = next(f for f in cat.fields("robot_scale") if f.name == "x0")
    assert x0.is_numeric and x0.min_value == -2000.0 and x0.max_value == 2000.0


def test_catalog_commands_device_hub(_discovered: None) -> None:
    cmds = NodeCatalog({}).commands("device_hub")
    assert "robot_draw_set_speed" in cmds
    assert "robot_draw_set_pen" in cmds


# --------------------------------------------------------------------------- #
# NodePickerDialog (Qt)
# --------------------------------------------------------------------------- #


def test_picker_builds_param_spec_for_angle(qtbot, _discovered: None) -> None:
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.picker import (
        NodePickerDialog,
    )

    topo = {
        "processes": [
            {
                "process_name": "points",
                "plugins": [{"plugin_name": "robot_scale", "category": "processing", "config": {"x0": 5.5}}],
            }
        ]
    }
    dlg = NodePickerDialog(NodeCatalog(topo))
    qtbot.addWidget(dlg)
    # Параметр по умолчанию; выбрать поле x0.
    idx = next(i for i in range(dlg._field_combo.count()) if dlg._field_combo.itemData(i).name == "x0")
    dlg._field_combo.setCurrentIndex(idx)
    dlg._on_accept()
    spec = dlg.result_spec()
    assert spec is not None
    assert spec["source"] == "param"
    assert spec["target_process"] == "points" and spec["target_field"] == "x0"
    assert spec["min"] == -2000.0 and spec["max"] == 2000.0
    assert spec["value"] == 5.5  # подтянуто из config ноды, а не min


def test_picker_builds_action_spec_for_speed(qtbot, _discovered: None) -> None:
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.picker import (
        NodePickerDialog,
    )

    topo = {"processes": [{"process_name": "devices", "plugins": [{"plugin_name": "device_hub", "category": "hub"}]}]}
    dlg = NodePickerDialog(NodeCatalog(topo))
    qtbot.addWidget(dlg)
    dlg._mode_action.setChecked(True)
    i = next(i for i in range(dlg._cmd_combo.count()) if dlg._cmd_combo.itemData(i) == "robot_draw_set_speed")
    dlg._cmd_combo.setCurrentIndex(i)
    dlg._action_ctype.setCurrentIndex(dlg._action_ctype.findData("slider"))
    dlg._value_arg.setText("pct")
    dlg._cmd_args.setText('{"device_id": "robot_main"}')
    dlg._on_accept()
    spec = dlg.result_spec()
    assert spec is not None
    assert spec["source"] == "action" and spec["target_command"] == "robot_draw_set_speed"
    assert spec["value_arg"] == "pct" and spec["command_args"] == {"device_id": "robot_main"}


def test_picker_param_str_field_uses_text_control(qtbot, _discovered: None) -> None:
    # Регресс: тип контрола следует типу поля — строковое registry_path → "text", не "number".
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.picker import (
        NodePickerDialog,
    )

    topo = {"processes": [{"process_name": "devices", "plugins": [{"plugin_name": "device_hub", "category": "hub"}]}]}
    dlg = NodePickerDialog(NodeCatalog(topo))
    qtbot.addWidget(dlg)
    i = next(i for i in range(dlg._field_combo.count()) if dlg._field_combo.itemData(i).name == "registry_path")
    dlg._field_combo.setCurrentIndex(i)
    dlg._on_accept()
    spec = dlg.result_spec()
    assert spec is not None
    assert spec["type"] == "text"


def test_picker_invalid_json_args_blocks_accept(qtbot, _discovered: None) -> None:
    from multiprocess_prototype.frontend.widgets.tabs.services.control_panel.picker import (
        NodePickerDialog,
    )

    topo = {"processes": [{"process_name": "devices", "plugins": [{"plugin_name": "device_hub", "category": "hub"}]}]}
    dlg = NodePickerDialog(NodeCatalog(topo))
    qtbot.addWidget(dlg)
    dlg._mode_action.setChecked(True)
    dlg._cmd_args.setText("{не json}")
    dlg._on_accept()
    assert dlg.result_spec() is None  # accept заблокирован, ошибка показана


# --------------------------------------------------------------------------- #
# Task 6.3: monitor — показ состояния чужой ноды (только чтение), РЕАЛЬНЫЙ GuiStateBindings
# --------------------------------------------------------------------------- #

_CTL_PATH = "processes.ctl.state.control_panel.controls"
_CONN_PATH = "devices.state.robot_main.conn"
_PARK_PATH = "devices.state.robot_main.park.state"
_MONITOR_TYPES = ["text", "number", "slider", "toggle", "select", "button"]
_REMOVE_MARK = "\u2715"  # «✕» — кнопка удаления ряда (есть у любого контрола)


class _MonitorReadModel:
    """read-model для replay: snapshot(prefix) → плоский кэш путь→значение."""

    def __init__(self) -> None:
        self.cache: dict = {}

    def snapshot(self, prefix: str) -> dict:
        if not prefix:
            return dict(self.cache)
        dotted = prefix + "."
        return {p: v for p, v in self.cache.items() if p == prefix or p.startswith(dotted)}


def _monitor(cid: str, path: str, key: str = "conn", label: str = "Связь", ctype: str = "text") -> dict:
    return {
        "id": cid,
        "type": ctype,
        "label": label,
        "source": "monitor",
        "target_process": "devices",
        "target_field": "conn",
        "state_path": path,
        "value_key": key,
    }


# Рецептоподобный набор: кнопка-action + param-число + monitor рядом (как в рецепте 1.0).
_HOME = {
    "id": "home",
    "type": "button",
    "label": "Домой",
    "source": "action",
    "target_process": "devices",
    "target_command": "robot_home",
}
_SPEED = {
    "id": "spd",
    "type": "number",
    "label": "Скорость",
    "source": "param",
    "target_process": "devices",
    "target_field": "speed",
}


class _Pult:
    """Реальные секция «Пульт» + GuiStateBindings; bridge/commands — записывающие заглушки."""

    def __init__(self, qtbot) -> None:
        self.qtbot = qtbot
        self.model = _MonitorReadModel()
        self.bindings = GuiStateBindings(MagicMock(), read_model=self.model)
        self.bridge = _RecBridge()
        self.services = _RecServices()
        runtime = SimpleNamespace(bindings=self.bindings, topology_bridge=self.bridge)
        self.section = build_control_panel_section(self.services, runtime).factory(None)

    def open(self):
        """Ленивое открытие вкладки: секция строит виджет и привязывает набор контролов."""
        widget = self.section.widget()
        self.qtbot.addWidget(widget)
        return widget

    def publish(self, path: str, value) -> None:
        self.model.cache[path] = value  # то, что увидит replay позже
        self.bindings._on_state_msg({"data_type": "state_delta", "path": path, "value": value})

    def settle(self) -> None:
        """Дать отработать отложенным пересвязкам и deleteLater старых рядов."""
        self.qtbot.wait(30)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.qtbot.wait(30)

    def handles_on(self, path: str) -> int:
        return sum(1 for h in self.bindings._bindings if h.pattern == path)


def _texts(widget) -> list[str]:
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


_INTERACTIVE = (QAbstractButton, QAbstractSpinBox, QAbstractSlider, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit)


def _interactive(widget) -> list:
    found: list = []
    for cls in _INTERACTIVE:
        for w in widget.findChildren(cls):
            if not any(w is f for f in found):  # QSpinBox виден и как QAbstractSpinBox
                found.append(w)
    return found


def _new_in_monitor_row(pult: _Pult, widget, ctype: str) -> list:
    """Интерактивные виджеты, появившиеся от monitor-контрола (минус статичная форма «Добавить»)."""
    base = _interactive(widget)
    pult.publish(_CTL_PATH, [_monitor("robot_conn", _CONN_PATH, ctype=ctype)])
    pult.settle()
    return [w for w in _interactive(widget) if not any(w is b for b in base)]


def _is_remove_button(w) -> bool:
    return isinstance(w, QAbstractButton) and w.text() == _REMOVE_MARK


def test_monitor_label_follows_state_delta(qtbot) -> None:
    pult = _Pult(qtbot)
    widget = pult.open()
    pult.publish(_CTL_PATH, [_HOME, _monitor("robot_conn", _CONN_PATH), _SPEED])
    pult.settle()
    assert "connected" not in _texts(widget)

    pult.publish(_CONN_PATH, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in _texts(widget), timeout=2000)

    pult.publish(_CONN_PATH, {"conn": "disconnected", "ts": 8})
    qtbot.waitUntil(lambda: "disconnected" in _texts(widget), timeout=2000)
    assert "connected" not in _texts(widget)  # старое значение заменено, а не дописано


def test_monitor_replay_on_lazy_bind(qtbot) -> None:
    pult = _Pult(qtbot)
    # дельты прошли ДО открытия вкладки (секция ещё не построена, привязок нет)
    pult.publish(_CTL_PATH, [_HOME, _monitor("robot_conn", _CONN_PATH), _SPEED])
    pult.publish(_CONN_PATH, {"conn": "connected", "ts": 7})
    pult.publish(_CONN_PATH, {"conn": "ready", "ts": 9})  # последнее значение
    assert pult.handles_on(_CONN_PATH) == 0

    widget = pult.open()
    qtbot.waitUntil(lambda: "ready" in _texts(widget), timeout=2000)
    assert "connected" not in _texts(widget)


def test_monitor_rebind_drops_old_handles(qtbot) -> None:
    pult = _Pult(qtbot)
    widget = pult.open()
    pult.publish(_CTL_PATH, [_monitor("robot_conn", _CONN_PATH)])
    pult.settle()
    pult.publish(_CONN_PATH, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in _texts(widget), timeout=2000)
    old_label = next(lbl for lbl in widget.findChildren(QLabel) if lbl.text() == "connected")
    assert pult.handles_on(_CONN_PATH) == 1

    # набор пересобран: monitor на conn убран, появился monitor на другой путь
    pult.publish(_CTL_PATH, [_monitor("robot_park", _PARK_PATH, key="", label="Парковка")])
    pult.settle()
    assert pult.handles_on(_CONN_PATH) == 0
    assert pult.handles_on(_PARK_PATH) == 1
    pult.publish(_CONN_PATH, {"conn": "STALE", "ts": 99})
    pult.settle()
    assert "STALE" not in _texts(widget)
    assert not isValid(old_label) or old_label.text() != "STALE"  # старая метка не обновляется

    # троекратная пересборка ОДНОГО и того же набора не копит handle
    for _ in range(3):
        pult.publish(_CTL_PATH, [_monitor("robot_conn", _CONN_PATH)])
        pult.settle()
    assert pult.handles_on(_CONN_PATH) == 1
    assert pult.handles_on(_PARK_PATH) == 0


@pytest.mark.parametrize("ctype", _MONITOR_TYPES)
def test_monitor_row_has_no_editable_widgets(qtbot, ctype: str) -> None:
    pult = _Pult(qtbot)
    widget = pult.open()
    new = _new_in_monitor_row(pult, widget, ctype)
    offenders = [type(w).__name__ for w in new if not _is_remove_button(w)]
    assert offenders == []  # допустима только кнопка удаления «✕»; значение — QLabel
    pult.publish(_CONN_PATH, {"conn": "connected", "ts": 7})
    qtbot.waitUntil(lambda: "connected" in _texts(widget), timeout=2000)  # и значение действительно в QLabel


@pytest.mark.parametrize("value", [{"conn": "connected", "ts": 7}, {"ts": 7}, {}, "idle", None])
def test_monitor_formatter_tolerates_non_dict(qtbot, value) -> None:
    pult = _Pult(qtbot)
    widget = pult.open()
    # два monitor на ОДИН путь: первый (value_key=conn) не должен ронять цикл дельт для второго.
    pult.publish(
        _CTL_PATH, [_monitor("a", _CONN_PATH, key="conn", label="A"), _monitor("b", _CONN_PATH, key="", label="B")]
    )
    pult.settle()
    assert pult.handles_on(_CONN_PATH) == 2
    pult.publish(_CONN_PATH, value)  # исключение форматтера вышло бы из _on_state_msg и упало бы здесь
    pult.settle()
    if isinstance(value, dict) and "conn" in value:
        assert "connected" in _texts(widget)  # dict: берётся value[value_key], без «ts»
    # цикл дельт жив: второй monitor (value_key пуст → само значение) принимает следующую дельту
    pult.publish(_CONN_PATH, "after")
    qtbot.waitUntil(lambda: _texts(widget).count("after") >= 1, timeout=2000)


@pytest.mark.parametrize("ctype", _MONITOR_TYPES)
@pytest.mark.timeout(20)
def test_monitor_never_dispatches(qtbot, monkeypatch, ctype: str) -> None:
    # «✕» открывает модальный QMessageBox — глушим, чтобы тест не мог зависнуть на диалоге.
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    pult = _Pult(qtbot)
    widget = pult.open()
    new = _new_in_monitor_row(pult, widget, ctype)

    # (1) пользователь «давит» на всё интерактивное в ряду monitor (кроме «✕»), если оно там есть
    for w in new:
        if _is_remove_button(w):
            continue
        if isinstance(w, QLineEdit):
            w.setText("x")
            w.returnPressed.emit()
        elif isinstance(w, QAbstractButton):
            w.click()
        elif isinstance(w, QAbstractSlider):
            w.setValue(w.maximum())
        elif isinstance(w, QAbstractSpinBox):
            if hasattr(w, "setValue"):
                w.setValue(w.maximum())
            w.editingFinished.emit()
        elif isinstance(w, QComboBox):
            w.activated.emit(0)
    # (2) и прямой эмит операции от виджета пульта
    widget.control_operated.emit("robot_conn", "x")
    widget.control_operated.emit("robot_conn", True)
    widget.control_operated.emit("robot_conn", 5.0)
    pult.settle()

    assert pult.bridge.actions == []  # 0 вызовов bridge.on_action_command
    assert [c for c in pult.services.commands.dispatched if isinstance(c, SetPluginConfig)] == []
    assert pult.services.commands.dispatched == []
