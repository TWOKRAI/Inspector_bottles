"""Тесты для frontend/state/bindings.py.

Используют pytest-qt (qtbot) для создания реальных Qt-виджетов.
Bridge мокается через MagicMock — важно убедиться, что
set_state_callback был вызван при инициализации GuiStateBindings.

Сообщения синтезируются вызовом bindings._on_state_msg() напрямую.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel, QSpinBox

from multiprocess_prototype.frontend.state.bindings import GuiStateBindings


# ---------------------------------------------------------------------------
# Вспомогательный fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge():
    """Мок DataReceiverBridge с методом set_state_callback."""
    mock = MagicMock()
    return mock


@pytest.fixture
def bindings(bridge):
    """Экземпляр GuiStateBindings с мок-bridge."""
    return GuiStateBindings(bridge)


# ---------------------------------------------------------------------------
# Инициализация
# ---------------------------------------------------------------------------


class TestInit:
    """Проверка инициализации GuiStateBindings."""

    def test_set_state_callback_called_on_init(self, bridge):
        """GuiStateBindings.__init__ должен вызвать bridge.set_state_callback."""
        b = GuiStateBindings(bridge)
        bridge.set_state_callback.assert_called_once_with(b._on_state_msg)


# ---------------------------------------------------------------------------
# Базовые property setters
# ---------------------------------------------------------------------------


class TestPropertySetters:
    """Проверка применения setter-ов при получении state_delta."""

    def test_bind_value_property_updates_spinbox(self, qtbot, bindings):
        """Базовый кейс: prop='value' → spinbox.setValue()."""
        spinbox = QSpinBox()
        qtbot.addWidget(spinbox)

        bindings.bind("processes.cam.state.fps", spinbox, "value")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": 42,
            }
        )

        assert spinbox.value() == 42

    def test_gui_local_metric_feeds_binding(self, qtbot, bindings):
        """Ф5.19: data_type='gui_local_metric' питает те же path-биндинги (замена fake state_delta)."""
        label = QLabel()
        qtbot.addWidget(label)

        bindings.bind("system.chain_fps", label, "text", formatter=lambda v: f"FPS {v}")
        bindings._on_state_msg(
            {
                "data_type": "gui_local_metric",
                "path": "system.chain_fps",
                "value": 30.0,
            }
        )

        assert label.text() == "FPS 30.0"

    def test_bind_text_property_updates_label(self, qtbot, bindings):
        """prop='text' → label.setText()."""
        label = QLabel()
        qtbot.addWidget(label)

        bindings.bind("services.capture.status", label, "text")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "services.capture.status",
                "value": "running",
            }
        )

        assert label.text() == "running"

    def test_bind_checked_property_updates_checkbox(self, qtbot, bindings):
        """prop='checked' → checkbox.setChecked()."""
        checkbox = QCheckBox()
        qtbot.addWidget(checkbox)
        checkbox.setChecked(False)

        bindings.bind("system.flags.enabled", checkbox, "checked")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "system.flags.enabled",
                "value": True,
            }
        )

        assert checkbox.isChecked() is True


# ---------------------------------------------------------------------------
# Glob-паттерны с несколькими подписчиками
# ---------------------------------------------------------------------------


class TestGlobMultipleSubscribers:
    """Проверка, что glob-паттерн срабатывает на нескольких виджетах."""

    def test_glob_pattern_matches_multiple_subscribers(self, qtbot, bindings):
        """Два виджета на 'processes.*.state.fps' — оба обновляются."""
        label1 = QLabel()
        label2 = QLabel()
        qtbot.addWidget(label1)
        qtbot.addWidget(label2)

        bindings.bind("processes.*.state.fps", label1, "text")
        bindings.bind("processes.*.state.fps", label2, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "25.3",
            }
        )

        assert label1.text() == "25.3"
        assert label2.text() == "25.3"


# ---------------------------------------------------------------------------
# Несовпадающий паттерн
# ---------------------------------------------------------------------------


class TestNoMatch:
    """Несовпадающий путь не должен вызывать setter."""

    def test_no_match_does_not_call_setter(self, qtbot, bindings):
        """Сообщение с path, не совпадающим с pattern — setter не вызывается."""
        label = QLabel("original")
        qtbot.addWidget(label)

        bindings.bind("processes.cam.state.fps", label, "text")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.config.fps",  # другой сегмент 'config' вместо 'state'
                "value": "updated",
            }
        )

        assert label.text() == "original"


# ---------------------------------------------------------------------------
# Авто-уборка мёртвых виджетов
# ---------------------------------------------------------------------------


class TestDestroyedWidget:
    """После уничтожения виджета подписка должна быть убрана."""

    def test_destroyed_widget_is_pruned(self, qtbot, bindings):
        """После deleteLater() + обработки событий отправка не вызывает ошибок,
        и мёртвый weakref убирается из списка подписок."""
        label = QLabel("initial")
        qtbot.addWidget(label)

        bindings.bind("processes.cam.state.fps", label, "text")
        assert len(bindings._bindings) == 1

        # Уничтожаем виджет
        label.deleteLater()
        # Обрабатываем события Qt — destroyed signal должен прийти
        qtbot.wait(50)

        # Отправляем сообщение — не должно быть исключений
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )
        # Список должен быть очищен (либо через signal, либо через прунинг в _on_state_msg)
        assert len(bindings._bindings) == 0


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    """Formatter применяется до setter."""

    def test_formatter_applied_before_set(self, qtbot, bindings):
        """formatter=lambda v: f'{v:.1f}' → label получает строку '25.3'."""
        label = QLabel()
        qtbot.addWidget(label)

        bindings.bind(
            "processes.cam.state.fps",
            label,
            "text",
            formatter=lambda v: f"{v:.1f}",
        )
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": 25.3,
            }
        )

        assert label.text() == "25.3"


# ---------------------------------------------------------------------------
# Unbind
# ---------------------------------------------------------------------------


class TestUnbind:
    """unbind(handle) удаляет подписку, setter больше не вызывается."""

    def test_unbind_handle_removes_binding(self, qtbot, bindings):
        """После unbind(handle) сообщения не обновляют виджет."""
        label = QLabel("initial")
        qtbot.addWidget(label)

        handle = bindings.bind("processes.cam.state.fps", label, "text")

        # Убеждаемся, что до unbind — работает
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )
        assert label.text() == "updated"

        # Снимаем подписку
        bindings.unbind(handle)

        # Сообщение после unbind не должно изменить виджет
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "should_not_appear",
            }
        )
        assert label.text() == "updated"


# ---------------------------------------------------------------------------
# Игнорирование некорректных сообщений
# ---------------------------------------------------------------------------


class TestIgnoreInvalidMessages:
    """Сообщения без обязательных полей — тихо игнорируются."""

    def test_wrong_data_type_ignored(self, qtbot, bindings):
        """data_type != 'state_delta' → игнорируется."""
        label = QLabel("original")
        qtbot.addWidget(label)
        bindings.bind("processes.cam.state.fps", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "frame_ready",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )

        assert label.text() == "original"

    def test_missing_path_ignored(self, qtbot, bindings):
        """Нет ключа 'path' — игнорируется."""
        label = QLabel("original")
        qtbot.addWidget(label)
        bindings.bind("processes.cam.state.fps", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "value": "updated",
            }
        )

        assert label.text() == "original"


# ---------------------------------------------------------------------------
# Delete-дельта (5.9: полный Delta до биндингов)
# ---------------------------------------------------------------------------


class TestDeleteDelta:
    """delete-дельта (deleted=True) доходит до биндингов и обрабатывается."""

    def test_delete_without_reset_does_not_push_garbage(self, qtbot, bindings):
        """reset не задан → при удалении виджет не трогаем (никакого None/MISSING)."""
        label = QLabel("original")
        qtbot.addWidget(label)
        bindings.bind("processes.cam.state.status", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.status",
                "value": None,
                "deleted": True,
            }
        )

        # Значение НЕ затёрто "None"/"MISSING" — удаление доставлено, но не мусорит
        assert label.text() == "original"

    def test_delete_with_reset_applies_reset(self, qtbot, bindings):
        """reset задан → при удалении применяется reset-значение."""
        spinbox = QSpinBox()
        qtbot.addWidget(spinbox)
        spinbox.setValue(42)

        bindings.bind("processes.cam.state.fps", spinbox, "value", reset=0)

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": None,
                "deleted": True,
            }
        )

        assert spinbox.value() == 0

    def test_delete_with_reset_none_via_formatter(self, qtbot, bindings):
        """reset=None + formatter → удаление отображает 'пусто' (различимо от set)."""
        label = QLabel("running")
        qtbot.addWidget(label)

        bindings.bind(
            "processes.cam.state.status",
            label,
            "text",
            formatter=lambda v: "—" if v is None else str(v),
            reset=None,
        )

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.status",
                "value": None,
                "deleted": True,
            }
        )

        assert label.text() == "—"

    def test_set_none_value_still_applied(self, qtbot, bindings):
        """deleted=False + value=None → обычный set (None различим от удаления)."""
        label = QLabel("running")
        qtbot.addWidget(label)

        bindings.bind("processes.cam.state.status", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.status",
                "value": None,
                "deleted": False,
            }
        )

        # set None → setText(str(None)) = "None" (это НЕ удаление)
        assert label.text() == "None"


# ---------------------------------------------------------------------------
# Авто-подписка bind ↔ ensure/release_subscription (5.9)
# ---------------------------------------------------------------------------


class TestAutoSubscription:
    """bind()/unbind() дёргают ensure/release_subscription с pattern."""

    def _make(self, bridge):
        ensure = MagicMock()
        release = MagicMock()
        b = GuiStateBindings(bridge, ensure_subscription=ensure, release_subscription=release)
        return b, ensure, release

    def test_bind_calls_ensure_with_pattern(self, qtbot, bridge):
        b, ensure, _ = self._make(bridge)
        label = QLabel()
        qtbot.addWidget(label)
        b.bind("processes.cam.state.fps", label, "text")
        ensure.assert_called_once_with("processes.cam.state.fps")

    def test_unbind_calls_release_with_pattern(self, qtbot, bridge):
        b, _, release = self._make(bridge)
        label = QLabel()
        qtbot.addWidget(label)
        handle = b.bind("processes.cam.state.fps", label, "text")
        b.unbind(handle)
        release.assert_called_once_with("processes.cam.state.fps")

    def test_unbind_widget_releases_each_binding(self, qtbot, bridge):
        b, _, release = self._make(bridge)
        label = QLabel()
        qtbot.addWidget(label)
        b.bind("a.b", label, "text")
        b.bind("c.d", label, "text")
        b.unbind_widget(label)
        assert release.call_count == 2
        released = {c.args[0] for c in release.call_args_list}
        assert released == {"a.b", "c.d"}

    def test_fanout_bind_unbind_ensure_release(self, qtbot, bridge):
        b, ensure, release = self._make(bridge)
        h = b.bind_fanout("processes.*.workers.*.status", lambda p, v: None)
        ensure.assert_called_once_with("processes.*.workers.*.status")
        b.unbind_fanout(h)
        release.assert_called_once_with("processes.*.workers.*.status")

    def test_double_unbind_releases_once(self, qtbot, bridge):
        b, _, release = self._make(bridge)
        label = QLabel()
        qtbot.addWidget(label)
        handle = b.bind("a.b", label, "text")
        b.unbind(handle)
        b.unbind(handle)  # повторный — no-op, без второго release
        release.assert_called_once_with("a.b")

    def test_no_callbacks_configured_is_safe(self, qtbot, bridge):
        """Без ensure/release (legacy) bind/unbind работают как раньше."""
        b = GuiStateBindings(bridge)  # без колбэков
        label = QLabel()
        qtbot.addWidget(label)
        handle = b.bind("a.b", label, "text")
        b.unbind(handle)  # не падает


# ---------------------------------------------------------------------------
# Replay из кэша при bind() (Task 4.1)
# ---------------------------------------------------------------------------


class TestCacheReplayOnBind:
    """bind() сразу применяет закэшированное значение (ленивые вкладки)."""

    def test_exact_path_replayed_immediately(self, qtbot, bridge):
        """bind на путь с уже закэшированным значением → setter сразу."""
        cache = {"processes.cam.state.status": "running"}
        b = GuiStateBindings(bridge, cache_snapshot=lambda: dict(cache))

        label = QLabel("—")
        qtbot.addWidget(label)
        b.bind("processes.cam.state.status", label, "text")

        # значение применено БЕЗ прихода новой дельты
        assert label.text() == "running"

    def test_glob_pattern_replays_all_matches(self, qtbot, bridge):
        """glob-паттерн → replay всех совпадающих путей из снимка кэша."""
        cache = {
            "processes.cam.workers.w1.status": "running",
            "processes.cam.workers.w2.status": "paused",
            "processes.other.state.fps": 30,  # не должен матчить
        }
        b = GuiStateBindings(bridge, cache_snapshot=lambda: dict(cache))

        label = QLabel("—")
        qtbot.addWidget(label)
        # последнее совпадение из снимка станет финальным текстом
        b.bind("processes.cam.workers.*.status", label, "text")

        assert label.text() in ("running", "paused")

    def test_no_cached_value_keeps_default(self, qtbot, bridge):
        """Путь не в кэше → виджет остаётся с дефолтом."""
        b = GuiStateBindings(bridge, cache_snapshot=lambda: {})
        label = QLabel("—")
        qtbot.addWidget(label)
        b.bind("processes.cam.state.status", label, "text")
        assert label.text() == "—"

    def test_no_cache_snapshot_legacy_no_replay(self, qtbot, bridge):
        """cache_snapshot=None → bind работает как раньше (без replay)."""
        b = GuiStateBindings(bridge)  # без cache_snapshot
        label = QLabel("—")
        qtbot.addWidget(label)
        b.bind("processes.cam.state.status", label, "text")
        assert label.text() == "—"

    def test_cache_snapshot_exception_does_not_break_bind(self, qtbot, bridge):
        """Исключение в провайдере снимка → bind не падает."""

        def boom():
            raise RuntimeError("cache unavailable")

        b = GuiStateBindings(bridge, cache_snapshot=boom)
        label = QLabel("—")
        qtbot.addWidget(label)
        # не должно бросить
        b.bind("processes.cam.state.status", label, "text")
        assert label.text() == "—"


# ---------------------------------------------------------------------------
# Fan-out: динамическое обнаружение ключей (рантайм-воркеры)
# ---------------------------------------------------------------------------


class TestFanout:
    """bind_fanout: callback(path, value) на каждую matching дельту."""

    def test_fanout_called_on_matching_delta(self, bindings):
        seen: list[tuple[str, object]] = []
        bindings.bind_fanout(
            "processes.detector.workers.*.status",
            lambda p, v: seen.append((p, v)),
        )
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.detector.workers.data_receiver.status",
                "value": "running",
            }
        )
        assert seen == [("processes.detector.workers.data_receiver.status", "running")]

    def test_fanout_ignores_nonmatching_path(self, bindings):
        seen: list[str] = []
        bindings.bind_fanout(
            "processes.detector.workers.*.status",
            lambda p, v: seen.append(p),
        )
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.detector.state.fps",
                "value": 20,
            }
        )
        assert seen == []

    def test_fanout_replays_cache_on_register(self, bridge):
        cache = {"processes.detector.workers.pipeline_executor.status": "running"}
        b = GuiStateBindings(bridge, cache_snapshot=lambda: cache)
        seen: list[tuple[str, object]] = []
        b.bind_fanout(
            "processes.detector.workers.*.status",
            lambda p, v: seen.append((p, v)),
        )
        assert seen == [("processes.detector.workers.pipeline_executor.status", "running")]


# ---------------------------------------------------------------------------
# Fan-out: явная отписка (unbind_fanout / unbind_by_owner)
# ---------------------------------------------------------------------------


class TestFanoutUnbind:
    """bind_fanout возвращает хэндл; unbind_fanout/unbind_by_owner снимают подписки."""

    def test_bind_fanout_returns_handle(self, bindings):
        """bind_fanout возвращает не-None хэндл (для последующего unbind_fanout)."""
        handle = bindings.bind_fanout("a.*", lambda p, v: None)
        assert handle is not None

    def test_unbind_fanout_stops_callbacks(self, bindings):
        """После unbind_fanout(handle) callback больше не вызывается."""
        seen: list[str] = []
        handle = bindings.bind_fanout("a.*", lambda p, v: seen.append(p))

        bindings._on_state_msg({"data_type": "state_delta", "path": "a.x", "value": 1})
        assert seen == ["a.x"]

        bindings.unbind_fanout(handle)
        bindings._on_state_msg({"data_type": "state_delta", "path": "a.y", "value": 2})
        assert seen == ["a.x"]  # новых вызовов нет

    def test_unbind_fanout_idempotent(self, bindings):
        """Повторный unbind_fanout того же хэндла — не падает."""
        handle = bindings.bind_fanout("a.*", lambda p, v: None)
        bindings.unbind_fanout(handle)
        bindings.unbind_fanout(handle)  # не должно бросить
        assert bindings._fanouts == []

    def test_unbind_fanout_removes_only_its_subscription(self, bindings):
        """Два одинаковых bind_fanout → unbind снимает ИМЕННО свой хэндл (identity, не equality).

        Снимаем ВТОРОЙ хэндл: list.remove по equality удалил бы первый по
        позиции, поэтому тест жёстко фиксирует eq=False у FanoutHandle.
        """
        seen: list[str] = []
        cb = lambda p, v: seen.append(p)  # noqa: E731
        h1 = bindings.bind_fanout("a.*", cb)
        h2 = bindings.bind_fanout("a.*", cb)

        bindings.unbind_fanout(h2)
        assert bindings._fanouts == [h1]  # остался именно первый хэндл
        bindings._on_state_msg({"data_type": "state_delta", "path": "a.x", "value": 1})
        assert seen == ["a.x"]  # осталась ровно одна подписка

    def test_unbind_by_owner_removes_all_owner_subscriptions(self, qtbot, bindings):
        """unbind_by_owner снимает ВСЕ подписки владельца, чужие — не трогает."""
        from PySide6.QtWidgets import QLabel

        owner = QLabel()
        other = QLabel()
        qtbot.addWidget(owner)
        qtbot.addWidget(other)

        seen_owner: list[str] = []
        seen_other: list[str] = []
        seen_free: list[str] = []
        bindings.bind_fanout("a.*", lambda p, v: seen_owner.append(p), owner=owner)
        bindings.bind_fanout("b.*", lambda p, v: seen_owner.append(p), owner=owner)
        bindings.bind_fanout("a.*", lambda p, v: seen_other.append(p), owner=other)
        bindings.bind_fanout("a.*", lambda p, v: seen_free.append(p))  # без владельца

        bindings.unbind_by_owner(owner)

        bindings._on_state_msg({"data_type": "state_delta", "path": "a.x", "value": 1})
        bindings._on_state_msg({"data_type": "state_delta", "path": "b.x", "value": 2})

        assert seen_owner == []  # все подписки owner'а сняты
        assert seen_other == ["a.x"]  # чужая жива
        assert seen_free == ["a.x"]  # безвладельческая жива

    def test_owner_destroyed_auto_unbinds(self, qtbot, bindings):
        """destroyed владельца снимает fanout-подписку (авто-уборка через unbind_fanout)."""
        from PySide6.QtWidgets import QLabel

        owner = QLabel()
        qtbot.addWidget(owner)
        seen: list[str] = []
        bindings.bind_fanout("a.*", lambda p, v: seen.append(p), owner=owner)
        assert len(bindings._fanouts) == 1

        owner.deleteLater()
        qtbot.wait(50)  # даём Qt обработать destroyed

        assert bindings._fanouts == []
        bindings._on_state_msg({"data_type": "state_delta", "path": "a.x", "value": 1})
        assert seen == []

    def test_manual_unbind_then_owner_destroyed_safe(self, qtbot, bindings):
        """Ручной unbind_fanout + последующий destroyed владельца — не падает."""
        from PySide6.QtWidgets import QLabel

        owner = QLabel()
        qtbot.addWidget(owner)
        handle = bindings.bind_fanout("a.*", lambda p, v: None, owner=owner)
        bindings.unbind_fanout(handle)

        owner.deleteLater()
        qtbot.wait(50)  # авто-уборка по destroyed идемпотентна

        assert bindings._fanouts == []


# ---------------------------------------------------------------------------
# Review-фиксы 5.20: reap→release (#1), fan-out DELETED (#2)
# ---------------------------------------------------------------------------


class TestReviewFixes:
    def test_reap_dead_widget_releases_subscription(self, qtbot, bridge):
        """#1: уборка мёртвого weakref-биндинга отпускает подписку (нет leak).

        widget.destroyed.connect(lambda) в bind() держит strong-ref на виджет,
        поэтому reap-путь в жизни редок (обычно раньше срабатывает destroyed→
        unbind_widget). Инжектируем мёртвый weakref, чтобы проверить именно
        reap→_release: без него refcount паттерна утёк бы.
        """
        ensure, release = MagicMock(), MagicMock()
        b = GuiStateBindings(bridge, ensure_subscription=ensure, release_subscription=release)
        w = QLabel()
        qtbot.addWidget(w)
        handle = b.bind("a.b", w, "text")
        ensure.assert_called_once_with("a.b")

        # Симулируем «виджет собран GC»: weakref теперь возвращает None
        handle.widget_ref = lambda: None
        b._on_state_msg({"data_type": "state_delta", "path": "a.b", "value": 1})

        assert handle not in b._bindings  # reap убрал
        release.assert_called_once_with("a.b")

    def test_fanout_receives_DELETED_sentinel_on_delete(self, qtbot, bindings):
        """#2: fan-out получает sentinel DELETED на delete (не None)."""
        from multiprocess_prototype.frontend.state.bindings import DELETED

        seen: list = []
        bindings.bind_fanout("proc.*.workers.*", lambda p, v: seen.append((p, v)))

        bindings._on_state_msg(
            {"data_type": "state_delta", "path": "proc.cam.workers.w1", "value": None, "deleted": True}
        )
        assert seen == [("proc.cam.workers.w1", DELETED)]

        seen.clear()
        bindings._on_state_msg(
            {"data_type": "state_delta", "path": "proc.cam.workers.w1", "value": 42, "deleted": False}
        )
        assert seen == [("proc.cam.workers.w1", 42)]


# ---------------------------------------------------------------------------
# Интеграция реального GUI-пути доставки (Ф-GUI-read-model 0.1/0.2, угловое ревью)
# ---------------------------------------------------------------------------


class _SyncBridge:
    """Синхронный дубль DataReceiverBridge для state-пути.

    В проде bridge лишь МАРШАЛИТ поток IO→Qt (QueuedConnection), содержимое
    state_delta-сообщения не меняет. Здесь маршалинг убран (тест однопоточный):
    dispatch state-сообщения сразу зовёт зарегистрированный state-callback —
    ровно то, что делает настоящий bridge для data_type='state_delta'.
    """

    def __init__(self) -> None:
        self._state_cb = None
        self._state_listeners: list = []

    def set_state_callback(self, cb) -> None:
        self._state_cb = cb

    def add_state_listener(self, cb) -> None:
        self._state_listeners.append(cb)

    def dispatch(self, msg_dict: dict) -> None:
        # Только state-путь — как реальный bridge для state_delta/gui_local_metric.
        if self._state_cb is not None:
            self._state_cb(msg_dict)
        for cb in list(self._state_listeners):
            cb(msg_dict)


class _ConfirmingRouter:
    """Мок-router: sync subscribe подтверждается валидным sub_id (как прод-сервер).

    Позволяет проверить, что покрывающий wildcard реально ПОДТВЕРЖДЁН и покрывает
    узкий bind (0 новых серверных subscribe), а доставка идёт GUI-путём.
    """

    def __init__(self) -> None:
        self.async_subscribes: list = []
        self._seq = 0

    def register_message_handler(self, *a, **k) -> None:
        pass

    def send_async(self, msg, priority: str = "normal") -> None:
        if isinstance(msg, dict) and msg.get("command") == "state.subscribe":
            self.async_subscribes.append(msg)

    def request(self, msg, timeout: float = 5.0) -> dict:
        self._seq += 1
        return {"success": True, "result": {"status": "ok", "sub_id": f"srv-{self._seq}"}}


class TestGuiDeliveryPathIntegration:
    """Доставка узкому bind, покрытому подтверждённым wildcard, РЕАЛЬНЫМ GUI-путём.

    Путь: сервер шлёт state.changed → GuiStateProxy.on_state_changed →
    delta_sink(deltas) → bridge.dispatch(state_delta_message) → GuiStateBindings
    ._on_state_msg (свой матчер) → setter виджета. _invoke_callbacks НЕ участвует
    (delta_sink его подменяет) — именно этот путь ранее не был покрыт тестом.
    """

    def test_covered_narrow_bind_receives_live_update_via_gui_path(self, qtbot):
        from multiprocess_framework.modules.state_store_module.core.delta import Delta
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import (
            GuiStateProxy,
        )
        from multiprocess_prototype.frontend.state.delta_message import state_delta_message

        bridge = _SyncBridge()
        router = _ConfirmingRouter()

        # delta_sink — точная копия прод-GuiProcess._on_state_deltas_to_bridge.
        proxy = GuiStateProxy(
            "gui",
            router=router,
            delta_sink=lambda deltas: [bridge.dispatch(state_delta_message(d)) for d in deltas],
        )

        # Стартовый wildcard sync=True (как в frontend/process.py) → ПОДТВЕРЖДЁН.
        proxy.subscribe("processes.**", lambda _d: None, exclude_self=True)
        assert "processes.**" in proxy._confirmed_patterns

        # GuiStateBindings с авто-подпиской через ensure_subscription proxy.
        bindings = GuiStateBindings(
            bridge,
            ensure_subscription=proxy.ensure_subscription,
            release_subscription=proxy.release_subscription,
        )

        label = QLabel()
        qtbot.addWidget(label)
        # Узкий bind — покрыт подтверждённым processes.**: своей серверной подписки нет.
        bindings.bind("processes.cam.state.fps", label, "text")
        assert router.async_subscribes == [], "covered bind не должен слать серверный subscribe"

        # Сервер шлёт дельту по покрытому пути → должна дойти до виджета GUI-путём.
        delta = Delta(path="processes.cam.state.fps", old_value=None, new_value=30, source="camera")
        proxy.on_state_changed({"data": {"deltas": [delta.to_dict()]}})

        assert label.text() == "30"
