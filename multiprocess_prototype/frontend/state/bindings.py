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

# Sentinel: «reset-значение для delete не задано». Отличает «сбрасывать в None»
# (reset=None) от «не трогать виджет при удалении» (reset не передан).
_UNSET: Any = object()


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
        reset: значение, применяемое к виджету при удалении узла
            (delete-дельта). _UNSET (по умолчанию) → виджет при удалении не
            трогаем (только не пушим мусор). reset=None → сбросить в None
            (через formatter/setter).
    """

    pattern: str
    widget_ref: weakref.ref
    prop: str
    formatter: Callable[[Any], Any] | None = None
    reset: Any = _UNSET


# ---------------------------------------------------------------------------
# FanoutHandle — дескриптор одной fan-out подписки
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class FanoutHandle:
    """Дескриптор одной fan-out подписки (см. ``bind_fanout``).

    Сравнение — по идентичности (eq=False): два bind_fanout с одинаковыми
    аргументами дают РАЗНЫЕ хэндлы, unbind_fanout снимает ровно свою подписку.

    Attributes:
        pattern: glob-паттерн пути StateStore.
        callback: вызывается как callback(path, value) на каждую matching дельту.
        owner_ref: weakref на виджет-владелец; None — подписка без владельца.
    """

    pattern: str
    callback: Callable[[str, Any], None]
    owner_ref: weakref.ref | None = None


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
        ensure_subscription: Callable[[str], Any] | None = None,
        release_subscription: Callable[[str], Any] | None = None,
    ) -> None:
        """Инициализировать и занять state_callback у bridge.

        Args:
            bridge: экземпляр DataReceiverBridge (уже инициализированный).
            cache_snapshot: опциональный провайдер снимка кэша состояния
                ({path: value}). Если задан, bind() сразу применяет к виджету
                последнее известное значение (replay) — закрывает разрыв
                ленивых вкладок, созданных после прохождения разовых дельт
                (Task 4.1). При None replay не выполняется (legacy-поведение).
            ensure_subscription: опциональный колбэк (обычно
                StateProxy.ensure_subscription) — bind()/bind_fanout() вызывают
                его на pattern, чтобы серверная подписка гарантированно
                существовала (авто-подписка, 5.9). Закрывает класс ошибок
                «панель мертва, забыли wildcard». refcount живёт в proxy.
            release_subscription: симметричный колбэк для unbind — снимает
                ссылку на подписку (при обнулении refcount proxy отписывается).
        """
        self._ensure_subscription = ensure_subscription
        self._release_subscription = release_subscription
        self._bindings: list[BindingHandle] = []
        # Fan-out подписки (FanoutHandle) — callback(path, value) на каждую
        # дельту с matching path. В отличие от bind (один виджет), позволяет
        # подписчику динамически создавать виджеты по обнаруженным ключам
        # (например строки рантайм-воркеров processes.X.workers.*).
        self._fanouts: list[FanoutHandle] = []
        self._cache_snapshot = cache_snapshot
        bridge.set_state_callback(self._on_state_msg)

    # ------------------------------------------------------------------
    # Авто-подписка (5.9): bind/unbind ↔ proxy.ensure/release_subscription
    # ------------------------------------------------------------------

    def _ensure(self, pattern: str) -> None:
        """Гарантировать серверную подписку на pattern (если задан колбэк)."""
        if self._ensure_subscription is None:
            return
        try:
            self._ensure_subscription(pattern)
        except Exception as exc:
            _logger.debug("bindings: ensure_subscription('%s') failed: %s", pattern, exc)

    def _release(self, pattern: str) -> None:
        """Снять ссылку на подписку pattern (если задан колбэк)."""
        if self._release_subscription is None:
            return
        try:
            self._release_subscription(pattern)
        except Exception as exc:
            _logger.debug("bindings: release_subscription('%s') failed: %s", pattern, exc)

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
        reset: Any = _UNSET,
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
            reset: значение, применяемое при удалении узла (delete-дельта).
                По умолчанию (_UNSET) удаление не меняет виджет — но дельта
                всё равно доставлена и классифицирована (никакого мусора
                вместо sentinel MISSING в виджет не попадёт).

        Returns:
            BindingHandle — дескриптор для последующего unbind().
        """
        handle = BindingHandle(
            pattern=path,
            widget_ref=weakref.ref(widget),
            prop=prop,
            formatter=formatter,
            reset=reset,
        )
        self._bindings.append(handle)

        # Авто-подписка: серверная подписка на pattern гарантированно есть.
        self._ensure(handle.pattern)

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
    ) -> FanoutHandle:
        """Подписать fan-out callback на glob-паттерн (динамическое обнаружение).

        В отличие от ``bind`` (привязка к одному виджету), fan-out вызывает
        ``callback(path, value)`` на КАЖДУЮ дельту с matching path. Это нужно,
        когда набор ключей заранее неизвестен — например рантайм-воркеры
        ``processes.{proc}.workers.*.status``: подписчик сам решает, создать ли
        новую строку для обнаруженного воркера.

        Сразу проигрывает закэшированные значения (replay) — как ``bind``, чтобы
        ленивые панели увидели уже опубликованные ключи.

        ВНИМАНИЕ: дедупа нет — повторный bind_fanout с теми же аргументами
        создаёт ВТОРУЮ подписку. Владелец жизненного цикла обязан снять старую
        через unbind_fanout(handle) / unbind_by_owner(owner).

        Args:
            pattern: glob-паттерн пути StateStore.
            callback: вызывается как callback(path, value) на каждую matching дельту.
            owner: опциональный виджет-владелец; при его destroyed подписка
                автоматически снимается (защита от dangling-callback).

        Returns:
            FanoutHandle — дескриптор для последующего unbind_fanout().
        """
        handle = FanoutHandle(
            pattern=pattern,
            callback=callback,
            owner_ref=weakref.ref(owner) if owner is not None else None,
        )
        self._fanouts.append(handle)

        # Авто-подписка на pattern fan-out (как для bind).
        self._ensure(pattern)

        if owner is not None:
            # Авто-уборка при уничтожении владельца — через идемпотентный
            # unbind_fanout: повторный вызов (после ручного unbind) безопасен.
            owner.destroyed.connect(lambda *_: self.unbind_fanout(handle))

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

        return handle

    def unbind_fanout(self, handle: FanoutHandle) -> None:
        """Снять конкретную fan-out подписку по дескриптору (идемпотентно).

        Args:
            handle: дескриптор, ранее возвращённый bind_fanout().
        """
        try:
            self._fanouts.remove(handle)
        except ValueError:
            return  # Уже снята — не падаем и не отпускаем подписку повторно
        self._release(handle.pattern)

    def unbind_by_owner(self, owner: QWidget) -> None:
        """Снять ВСЕ fan-out подписки данного виджета-владельца.

        Подписки без владельца (owner=None) не затрагиваются. Попутно
        выметаются хэндлы с уже умершим владельцем (weakref пуст) — их
        подписка в любом случае осиротела.

        Args:
            owner: виджет, переданный в bind_fanout(owner=...).
        """
        kept: list[FanoutHandle] = []
        removed: list[FanoutHandle] = []
        for h in self._fanouts:
            if h.owner_ref is None:
                kept.append(h)
                continue
            ref = h.owner_ref()
            if ref is None or ref is owner:
                removed.append(h)  # целевой владелец или мёртвый weakref — снять
                continue
            kept.append(h)
        self._fanouts = kept
        for h in removed:
            self._release(h.pattern)

    def unbind(self, handle: BindingHandle) -> None:
        """Удалить конкретную подписку по дескриптору.

        Args:
            handle: дескриптор, ранее возвращённый bind().
        """
        try:
            self._bindings.remove(handle)
        except ValueError:
            return  # Уже удалена — не падаем и не отпускаем подписку повторно
        self._release(handle.pattern)

    def unbind_widget(self, widget: QWidget) -> None:
        """Удалить все подписки для данного виджета.

        Вызывается автоматически по сигналу widget.destroyed,
        но может быть вызван и вручную.

        Args:
            widget: Qt-виджет, чьи подписки нужно снять.
        """
        removed = [h for h in self._bindings if h.widget_ref() is widget]
        self._bindings = [h for h in self._bindings if h.widget_ref() is not widget]
        for h in removed:
            self._release(h.pattern)

    def clear(self) -> None:
        """Снять ВСЕ подписки — и виджетные, и fan-out."""
        patterns = [h.pattern for h in self._bindings] + [h.pattern for h in self._fanouts]
        self._bindings.clear()
        self._fanouts.clear()
        for pat in patterns:
            self._release(pat)

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
        # Полный Delta (5.9): удаление узла отличается флагом deleted, а не
        # значением. При delete не пушим value (там None-заглушка envelope,
        # раньше — sentinel MISSING) в виджет: применяем reset подписки, если
        # задан; иначе виджет не трогаем (дельта всё равно доставлена).
        deleted = bool(msg_dict.get("deleted"))

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

            if deleted:
                if handle.reset is not _UNSET:
                    self._apply_to_widget(handle, handle.reset)
                # reset не задан → удаление доставлено, но виджет не трогаем
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
        for fanout in list(self._fanouts):
            if match_glob(fanout.pattern, path):
                try:
                    fanout.callback(path, value)
                except Exception as exc:
                    _logger.debug("bindings: fan-out callback failed on %s (pattern %s): %s", path, fanout.pattern, exc)

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
