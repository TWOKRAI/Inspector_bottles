"""bindings.py — Реактивные подписки виджетов на пути StateStore.

GuiStateBindings регистрирует обратные вызовы через DataReceiverBridge.set_state_callback().
При поступлении сообщения {'data_type': 'state_delta', 'path': '...', 'value': ...}
находит все подписки с matching pattern и вызывает setter соответствующего виджета.

Хранение виджетов — через weakref.ref для автоматической уборки при удалении.
Авто-уборка также через сигнал widget.destroyed.
"""

from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from .glob_match import match_glob

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge

# Несовместимость виджета со значением — ожидаемая ситуация (не валим GUI), но по
# правилу 5 не глушим молча: логируем на debug, чтобы видеть при отладке биндингов.
_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Property setters — маппинг имени свойства на вызов метода виджета
# ---------------------------------------------------------------------------

_PROP_SETTERS: dict[str, Callable[[QWidget, Any], None]] = {
    "value": lambda w, v: w.setValue(v),  # type: ignore[attr-defined]
    "text": lambda w, v: w.setText(str(v)),  # type: ignore[attr-defined]
    "checked": lambda w, v: w.setChecked(bool(v)),  # type: ignore[attr-defined]
    "currentText": lambda w, v: w.setCurrentText(str(v)),  # type: ignore[attr-defined]
    "plainText": lambda w, v: w.setPlainText(str(v)),  # type: ignore[attr-defined]
}


# ---------------------------------------------------------------------------
# BindingHandle — дескриптор одной подписки
# ---------------------------------------------------------------------------


@dataclass
class BindingHandle:
    """Дескриптор одной подписки виджета на путь StateStore.

    Attributes:
        pattern: glob-паттерн пути, например 'processes.*.state.fps'.
        widget_ref: weakref на Qt-виджет; None если виджет уже уничтожен.
        prop: имя свойства виджета ('value', 'text', 'checked', ...).
        formatter: опциональный конвертор значения перед применением setter.
    """

    pattern: str
    widget_ref: weakref.ref
    prop: str
    formatter: Callable[[Any], Any] | None = None


# ---------------------------------------------------------------------------
# GuiStateBindings — менеджер подписок
# ---------------------------------------------------------------------------


class GuiStateBindings:
    """Менеджер реактивных подписок GUI-виджетов на пути StateStore.

    Занимает слот DataReceiverBridge.set_state_callback.
    Qt QueuedConnection уже обеспечен в bridge — дополнительных мьютексов
    и перекидывания на main thread не нужно.

    Использование:
        bindings = GuiStateBindings(process._bridge)
        handle = bindings.bind("processes.cam.state.fps", fps_label, "text")
        # ... позже, при необходимости:
        bindings.unbind(handle)
    """

    def __init__(
        self,
        bridge: "DataReceiverBridge",
        cache_snapshot: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """Инициализировать и занять state_callback у bridge.

        Args:
            bridge: экземпляр DataReceiverBridge (уже инициализированный).
            cache_snapshot: опциональный провайдер снимка кэша состояния
                ({path: value}). Если задан, bind() сразу применяет к виджету
                последнее известное значение (replay) — закрывает разрыв
                ленивых вкладок, созданных после прохождения разовых дельт
                (Task 4.1). При None replay не выполняется (legacy-поведение).
        """
        self._bindings: list[BindingHandle] = []
        # Fan-out подписки: (pattern, callback) — callback(path, value) на каждую
        # дельту с matching path. В отличие от bind (один виджет), позволяет
        # подписчику динамически создавать виджеты по обнаруженным ключам
        # (например строки рантайм-воркеров processes.X.workers.*).
        self._fanouts: list[tuple[str, Callable[[str, Any], None]]] = []
        self._cache_snapshot = cache_snapshot
        bridge.set_state_callback(self._on_state_msg)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def bind(
        self,
        path: str,
        widget: QWidget,
        prop: str = "value",
        *,
        formatter: Callable[[Any], Any] | None = None,
    ) -> BindingHandle:
        """Подписать виджет на изменения по glob-паттерну.

        После вызова при каждом state_delta-сообщении с matching path
        будет вызван setter виджета.

        Args:
            path: glob-паттерн пути StateStore.
            widget: Qt-виджет, чьё свойство нужно обновлять.
            prop: имя свойства ('value', 'text', 'checked', 'currentText',
                  'plainText', или любой метод через getattr).
            formatter: опциональный конвертор; вызывается перед setter.

        Returns:
            BindingHandle — дескриптор для последующего unbind().
        """
        handle = BindingHandle(
            pattern=path,
            widget_ref=weakref.ref(widget),
            prop=prop,
            formatter=formatter,
        )
        self._bindings.append(handle)

        # Авто-уборка при уничтожении виджета Qt
        widget.destroyed.connect(lambda *_: self.unbind_widget(widget))

        # Replay: сразу применить последнее известное значение из кэша (Task 4.1).
        # Нужно для ленивых вкладок, созданных ПОСЛЕ прохождения разовых дельт
        # (например processes.X.state.status публикуется один раз при смене статуса).
        if self._cache_snapshot is not None:
            try:
                snapshot = self._cache_snapshot()
            except Exception:
                snapshot = {}
            for cached_path, cached_value in snapshot.items():
                if match_glob(handle.pattern, cached_path):
                    self._apply_to_widget(handle, cached_value)

        return handle

    def bind_fanout(
        self,
        pattern: str,
        callback: Callable[[str, Any], None],
        owner: QWidget | None = None,
    ) -> None:
        """Подписать fan-out callback на glob-паттерн (динамическое обнаружение).

        В отличие от ``bind`` (привязка к одному виджету), fan-out вызывает
        ``callback(path, value)`` на КАЖДУЮ дельту с matching path. Это нужно,
        когда набор ключей заранее неизвестен — например рантайм-воркеры
        ``processes.{proc}.workers.*.status``: подписчик сам решает, создать ли
        новую строку для обнаруженного воркера.

        Сразу проигрывает закэшированные значения (replay) — как ``bind``, чтобы
        ленивые панели увидели уже опубликованные ключи.

        Args:
            pattern: glob-паттерн пути StateStore.
            callback: вызывается как callback(path, value) на каждую matching дельту.
            owner: опциональный виджет-владелец; при его destroyed подписка
                автоматически снимается (защита от dangling-callback).
        """
        entry = (pattern, callback)
        self._fanouts.append(entry)

        if owner is not None:
            owner.destroyed.connect(lambda *_: self._fanouts.remove(entry) if entry in self._fanouts else None)

        # Replay закэшированных значений.
        if self._cache_snapshot is not None:
            try:
                snapshot = self._cache_snapshot()
            except Exception:
                snapshot = {}
            for cached_path, cached_value in snapshot.items():
                if match_glob(pattern, cached_path):
                    try:
                        callback(cached_path, cached_value)
                    except Exception:
                        pass

    def unbind(self, handle: BindingHandle) -> None:
        """Удалить конкретную подписку по дескриптору.

        Args:
            handle: дескриптор, ранее возвращённый bind().
        """
        try:
            self._bindings.remove(handle)
        except ValueError:
            pass  # Уже удалена — не падаем

    def unbind_widget(self, widget: QWidget) -> None:
        """Удалить все подписки для данного виджета.

        Вызывается автоматически по сигналу widget.destroyed,
        но может быть вызван и вручную.

        Args:
            widget: Qt-виджет, чьи подписки нужно снять.
        """
        self._bindings = [h for h in self._bindings if h.widget_ref() is not widget]

    def clear(self) -> None:
        """Снять все подписки (очистить список)."""
        self._bindings.clear()

    # ------------------------------------------------------------------
    # Внутренний callback для bridge
    # ------------------------------------------------------------------

    def _on_state_msg(self, msg_dict: dict) -> None:
        """Обработчик state-сообщений из DataReceiverBridge.

        Вызывается в Qt main thread (Qt QueuedConnection обеспечен bridge).

        Формат ожидаемого сообщения:
            {'data_type': 'state_delta', 'path': 'processes.cam.state.fps', 'value': 25.3}

        Сообщения с другим data_type или без ключей path/value — игнорируются.

        Args:
            msg_dict: словарь сообщения.
        """
        # Проверяем обязательные поля
        if msg_dict.get("data_type") != "state_delta":
            return
        path = msg_dict.get("path")
        if path is None or "value" not in msg_dict:
            return

        value = msg_dict["value"]

        # Собираем «мёртвые» дескрипторы для последующей уборки
        dead: list[BindingHandle] = []

        for handle in self._bindings:
            # Проверяем, жив ли виджет
            if handle.widget_ref() is None:
                dead.append(handle)
                continue

            # Проверяем совпадение паттерна
            if not match_glob(handle.pattern, path):
                continue

            self._apply_to_widget(handle, value)

        # Убираем мёртвые weakref-ы
        if dead:
            for d in dead:
                try:
                    self._bindings.remove(d)
                except ValueError:
                    pass

        # Fan-out: динамическое обнаружение ключей (создание строк подписчиком).
        for fpattern, fcallback in list(self._fanouts):
            if match_glob(fpattern, path):
                try:
                    fcallback(path, value)
                except Exception as exc:
                    _logger.debug("bindings: fan-out callback failed on %s (pattern %s): %s", path, fpattern, exc)

    def _apply_to_widget(self, handle: BindingHandle, value: Any) -> bool:
        """Применить значение к виджету подписки через setter.

        Общая логика для live-дельт (_on_state_msg) и replay из кэша (bind).

        Args:
            handle: дескриптор подписки.
            value: сырое значение (formatter применяется здесь).

        Returns:
            False если виджет уже уничтожен (weakref пуст), иначе True.
        """
        widget = handle.widget_ref()
        if widget is None:
            return False

        display_value = handle.formatter(value) if handle.formatter else value

        setter = _PROP_SETTERS.get(handle.prop)
        if setter is not None:
            try:
                setter(widget, display_value)
            except Exception as exc:
                _logger.debug("bindings: setter '%s' failed on %s: %s", handle.prop, handle.pattern, exc)
        else:
            # Fallback: getattr(widget, prop)(value)
            try:
                method = getattr(widget, handle.prop, None)
                if callable(method):
                    method(display_value)
            except Exception as exc:
                _logger.debug("bindings: fallback method '%s' failed on %s: %s", handle.prop, handle.pattern, exc)
        return True
