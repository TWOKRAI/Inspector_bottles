# -*- coding: utf-8 -*-
"""
ErrorManager — брат LoggerManager (общий предок LoggerCore) с severity-based routing.

Task 5.14 (CRM-развязка): ErrorManager наследует общий лог-слой ``LoggerCore``,
а НЕ ``LoggerManager`` (композиция общего слоя вместо IS-A). Оба — потомки
``LoggerCore`` → ``ChannelRoutingManager``.

Ключевые улучшения (Фаза 3 — CRM унификация):
  - _setup_level_routes() строит _level_to_channel: {level_str → channel_name}
    и регистрирует маршруты в self._dispatcher (из CRM) напрямую.
  - log() перегружает LoggerCore.log() для WARNING/ERROR/CRITICAL:
    → ищет channel_name через _level_to_channel (O(1))
    → пишет через buffer (если есть) или напрямую в channel
  - DEBUG/INFO → fallback на LoggerCore.log() (scope-based)
  - Результат: level routing теперь РЕАЛЬНО используется, не просто регистрируется.

Архитектурная аналогия:
  RouterManager:   message → channel_dispatcher(key=type) → IMessageChannel
  ErrorManager:    error   → _level_to_channel(key=level) → ILogChannel
"""

import traceback
from copy import deepcopy
from typing import Optional, Any, List, Union, Dict

from ...channel_routing_module import resolve_build_result
from ...channel_routing_module.levels import is_error_level, rank_of
from ...logger_module.core.log_config import LoggerManagerConfig, LogLevel, ScopeName
from ...logger_module.core.logger_core import LoggerCore
from ..configs.error_manager_config import ErrorManagerConfig
from ..interfaces import IErrorManager
from .error_config_assembly import expand_error_manager_config


#: С какого ранга запись принадлежит плоскости ошибок. WARNING, а не ERROR:
#: ``_setup_level_routes`` строит маршрут и для него, и именно WARNING+ ходят
#: severity-путём мимо гейта скоупа. Число берётся из общего реестра рангов —
#: своя константа здесь разъехалась бы с ``_setup_level_routes`` молча.
_SEVERITY_PLANE_RANK = rank_of("WARNING")

_DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "errors",
    "default_level": "WARNING",
    "enable_batching": True,
    "batch_size": 50,
    "batch_interval": 0.5,
    "channels": {
        "critical_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/critical.log",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 10,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/errors.log",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 5,
        },
        "warnings_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/warnings.log",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 5 * 1024 * 1024,
            "backup_count": 3,
        },
    },
}


def _normalize_error_config(
    config: Optional[Union[Dict[str, Any], LoggerManagerConfig, Any]],
) -> tuple[str, LoggerManagerConfig, bool]:
    """Преобразовать config → (manager_name, LoggerManagerConfig, include_stacktrace).

    Поддерживает: None | dict | ErrorManagerConfig | LoggerManagerConfig | build() → (name, dict).
    Плоские dict / ErrorManagerConfig проходят через :func:`expand_error_manager_config`.
    Вызывает TypeError для неизвестных типов.
    """
    manager_name = "ErrorManager"
    include_stacktrace = True

    if config is None:
        # Через ту же сборку, что и остальные пути: умолчания плоскости ошибок
        # (scopes/modules, резидуал P3) обязаны действовать и на ``config=None``,
        # иначе «дефолтный ErrorManager» и «ErrorManager из ErrorManagerConfig»
        # получаются разными менеджерами.
        # deepcopy: без него наружу уезжают ТЕ ЖЕ вложенные словари каналов
        # ``_DEFAULT_CONFIG``, и правка одного конфига до валидации утекает во
        # все последующие ``ErrorManager()``. Половина этой опасности была
        # закрыта deepcopy'ем скоупов, вторая осталась — поймано ревью Ф1.
        expanded = expand_error_manager_config(deepcopy(_DEFAULT_CONFIG))
        return manager_name, LoggerManagerConfig.model_validate(expanded), include_stacktrace

    if isinstance(config, LoggerManagerConfig):
        return manager_name, config, include_stacktrace

    if isinstance(config, ErrorManagerConfig):
        raw = config.model_dump()
        d = expand_error_manager_config(raw)
        manager_name = str(raw.get("manager_name", "ErrorManager"))
        include_stacktrace = bool(d.get("include_stacktrace", True))
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    if isinstance(config, dict):
        d = expand_error_manager_config(dict(config))
        include_stacktrace = bool(d.get("include_stacktrace", True))
        manager_name = str(d.get("manager_name", "ErrorManager"))
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    if hasattr(config, "build") and callable(config.build):
        # D1 (constructor-master Ф5-добор, ADR-CRM-008): разбор build()-объекта
        # делегирован общему resolve_build_result из channel_routing_module —
        # не переопределяем эту логику здесь (как раньше через голый unpack).
        resolved = resolve_build_result(config)
        if resolved is not None:
            resolved_name, d = resolved
            manager_name = resolved_name if resolved_name is not None else manager_name
        else:
            d = {}
        include_stacktrace = d.get("include_stacktrace", True)
        if hasattr(config, "include_stacktrace"):
            include_stacktrace = bool(config.include_stacktrace)
        d = expand_error_manager_config(d)
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    raise TypeError(
        f"config must be dict, LoggerManagerConfig, ErrorManagerConfig, or object"
        f" with build() -> (name, dict), got {type(config)}"
    )


class ErrorManager(LoggerCore, IErrorManager):
    """Менеджер ошибок с severity-based channel routing.

    Task 5.14: брат ``LoggerManager`` (оба — потомки ``LoggerCore``), а НЕ его
    наследник (композиция общего лог-слоя вместо IS-A). Общий слой берётся из
    ``LoggerCore``; специфика severity-routing добавляется здесь.

    Добавляет поверх LoggerCore:
      1. _level_to_channel: Dict[str, str] — прямой маппинг уровня → канал.
         WARNING → warnings_file, ERROR → errors_file, CRITICAL → critical_file.

      2. log() override — для WARNING/ERROR/CRITICAL использует _level_to_channel
         вместо scope-based routing. DEBUG/INFO идут через LoggerCore.log().
         Buffer-aware: если _buffer задан → enqueue, иначе прямой write().

      3. log_exception() — traceback + self.error().

    Жизненный цикл:
        em = ErrorManager()
        em = ErrorManager(config={"app_name": "my_app"})
        em = ErrorManager(config=ErrorManagerConfig(...))
        em.initialize()
        em.log_exception(exc, "context", module="my_module")
        em.shutdown()
    """

    def __init__(
        self,
        manager_name: str = "ErrorManager",
        process: Optional[Any] = None,
        config: Optional[Union[Dict[str, Any], LoggerManagerConfig, Any]] = None,
        config_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        resolved_name, log_config, include_stacktrace = _normalize_error_config(config)
        manager_name = resolved_name

        # Guard до super(): LoggerCore.__init__ дёргает self.log()/self.info() косвенно
        # (напр. _setup_module_channel → self.debug()), а переопределённый ErrorManager.log()
        # читает self._level_to_channel. Инициализируем его ДО super(), иначе AttributeError.
        # (Task 5.14: ErrorManager — брат LoggerManager через LoggerCore, singleton _instance
        #  живёт только на LoggerManager и здесь НЕ выставляется.)
        self._level_to_channel: Dict[str, str] = {}
        self._include_stacktrace = include_stacktrace

        super().__init__(
            manager_name=manager_name,
            process=process,
            config=log_config,
            config_manager=config_manager,
            managers=managers or {},
            **kwargs,
        )

        # R9: родитель положил в слепок для отката развёрнутый LoggerManagerConfig,
        # в котором нет include_stacktrace — это флаг ErrorManager, а не логгера.
        # Откат с такого слепка тихо ВКЛЮЧИЛ бы трейсбеки тому, кто их выключил.
        # Исходный ввод восстанавливает обе половины; None не подменяем — на нём
        # родительский слепок уже равен дефолту, к которому и надо возвращаться.
        if config is not None:
            self._last_applied_config = config

        # Маршруты строятся УЖЕ здесь, а не только в initialize(): между
        # конструктором и initialize() менеджер обязан писать ошибку в СВОЙ
        # файл, а не в приёмник последней инстанции.
        #
        # Прежняя редакция этого комментария утверждала, что без вызова ERROR
        # «был бы отклонён гейтом молча» и инвариант 1 был бы пробит. Ревью Ф1
        # это опровергло запуском: гейт severity-плоскости открыт по РАНГУ
        # безусловно (см. `_is_gate_open`), поэтому запись не теряется — её
        # ловит пол. Настоящее последствие мягче и всё равно нежелательно:
        # `errors_to_floor` 0 → 1 при пустом `errors.log`, то есть ошибка
        # уезжает в аварийный JSONL при живом штатном канале, а счётчик
        # поднимает ложный сигнал «маршрут ошибок сломан».
        #
        # Вызов идемпотентен, в initialize() он остаётся.
        self._setup_level_routes()

    def initialize(self) -> bool:
        result = super().initialize()
        if result:
            self._setup_level_routes()
        return result

    def _setup_level_routes(self) -> None:
        """Построить _level_to_channel: {уровень → имя канала}.

        После этого self._level_to_channel["ERROR"] == "errors_file" (O(1) в log()).

        **У каждого уровня есть запасной приёмник** — и это правило, а не набор
        частных случаев. Ревью Ф1 воспроизвело асимметрию: у ERROR запасного не
        было вовсе, и снятие ОДНОГО ``errors_file`` отправляло ошибку в пол при
        живом ``critical_file`` (``errors_to_floor`` 0 → 1, ``critical.log``
        пуст). Потери не было — пол сработал, счётчик виден, — но приёмник
        последней инстанции нужен для случая «приёмников нет», а не «приёмник
        есть, просто не тот». После P2 это состояние стало достижимым в
        рантайме одной командой, поэтому цепочка достроена.

        Направление запасного — к БОЛЕЕ важному файлу, никогда к менее важному:
        ERROR уходит в ``critical.log``, а не в ``warnings.log``. Файл
        предупреждений просматривают реже всех, и спрятать ошибку там значит
        потерять её на практике, формально ничего не потеряв.
        """
        self._level_to_channel = {}

        has_critical = self._channel_registry.get("critical_file") is not None
        has_errors = self._channel_registry.get("errors_file") is not None
        has_warnings = self._channel_registry.get("warnings_file") is not None

        if has_critical:
            self._level_to_channel["CRITICAL"] = "critical_file"
        elif has_errors:
            self._level_to_channel["CRITICAL"] = "errors_file"

        if has_errors:
            self._level_to_channel["ERROR"] = "errors_file"
        elif has_critical:
            self._level_to_channel["ERROR"] = "critical_file"

        if has_warnings:
            self._level_to_channel["WARNING"] = "warnings_file"
        elif has_errors:
            self._level_to_channel["WARNING"] = "errors_file"
        elif has_critical:
            self._level_to_channel["WARNING"] = "critical_file"

        self._warn_on_silenced_severity_routes()

    def routes_using_sink(self, name: str) -> List[str]:
        """Уровни severity-карты, ведущие в этот приёмник.

        Не скоупы: у этой плоскости приёмников в скоупах нет по определению (P3),
        и ответ родителя перечислял бы маршруты, которых здесь не существует —
        то есть врал бы оператору ровно в тот момент, когда он решает, снимать ли
        канал.
        """
        target = str(name)
        return sorted(f"severity:{level}" for level, channel in self._level_to_channel.items() if channel == target)

    def _warn_on_silenced_severity_routes(self) -> None:
        """Severity-приёмник, ведущий в «никуда» (2.9) — свой аналог проверки родителя.

        Проверка родителя ходит по скоупам, а эта плоскость маршрутизирует
        severity-картой: у её скоупов приёмников нет по определению (P3),
        поэтому там смотреть не на что, и покрытие пришлось бы выдумать.
        Здесь смотрим по своей карте — на том же наборе понятий, каким плоскость
        реально решает, куда писать.

        Стоит в конце ``_setup_level_routes``, а не в ``_setup_channels``:
        карта строится ПОСЛЕ каналов, и в момент родительской проверки она
        ещё пуста. Пересборка маршрутов повторит предупреждение — это верно:
        конфигурация в этот момент заявлена заново.
        """
        for level, channel_name in sorted(self._level_to_channel.items()):
            if is_error_level(level) and self._all_null_sinks([channel_name]):
                self._warn_silenced_route(f"severity-маршрут {level}", [channel_name])

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """R9: разобрать error-конфиг ДО закрытия каналов.

        Свой override вместо родительского: ErrorManager принимает и плоский
        error-dict, и развёрнутый LoggerManagerConfig, и разбор у него свой
        (``expand_error_manager_config``). Родительский ``_resolve_log_config``
        на плоском error-dict молча вернул бы дефолтный конфиг — то есть
        «проверка», которая пропускает любую опечатку.
        """
        _normalize_error_config(config)

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук CRM.reconfigure: пересобрать каналы + перестроить severity-routing.

        Специфика ErrorManager поверх LoggerCore:
          - конфиг проходит через ``_normalize_error_config`` (принимает и плоский
            error-dict, и развёрнутый LoggerManagerConfig);
          - обновляется ``self._include_stacktrace``;
          - переиспользуется пересборка каналов родителя
            (``_apply_log_config_rebuild``), а затем перестраивается
            ``_level_to_channel`` через ``_setup_level_routes()`` — иначе
            severity-маршруты ссылались бы на закрытые каналы.
        """
        _name, log_config, include_stacktrace = _normalize_error_config(config)
        self._include_stacktrace = include_stacktrace
        self._apply_log_config_rebuild(log_config)
        self._setup_level_routes()

    def _on_channels_changed(self) -> None:
        """Состав каналов поменялся → severity-маршруты пересобрать (резидуал P2).

        Воспроизведение до правки: ``em.set_sink_enabled("critical_file", False)``
        → ``level_routes`` продолжал утверждать ``CRITICAL → critical_file``, хотя
        канала в реестре уже нет. Запись при этом не терялась (её ловил floor,
        ``errors_to_floor`` 0 → 1), но ``errors_file`` был ЖИВ — то есть вместо
        штатного маршрута ошибка уходила в приёмник последней инстанции, а
        публичный ``level_routes`` показывал маршрут, которого нет.

        Fallback-цепочка (``critical_file`` → ``errors_file``) считалась ровно
        один раз на ``initialize()``. Теперь она пересчитывается на каждом
        изменении состава — то есть ровно тогда, когда fallback и нужен.

        Родительский хук (сброс кэша решений) обязателен: ``_is_gate_open``
        здесь зависит от ``_level_to_channel``, а тот только что поменялся.
        """
        super()._on_channels_changed()
        self._setup_level_routes()

    def _is_gate_open(self, scope: ScopeName, level: LogLevel, module: str) -> bool:
        """Severity-плоскость открыта всегда; остальное решает скоуп (Ф1.3).

        Условие — «уровень принадлежит плоскости ошибок», а НЕ «для уровня
        сейчас есть канал». Разница стоила бы инварианта 1: канал у ERROR может
        исчезнуть (``sink.disable``), и завязка на его наличие закрывала бы
        гейт ровно в тот момент, когда запись обязана дойти хотя бы до пола.

        Пара к :meth:`_route`: гейт и резолв обязаны отвечать одинаково, иначе
        публичный ``is_enabled_for`` обещает одно, а ``log()`` делает другое.
        Сетка ``test_gate_predicate.py`` проверяет их согласие на каждой паре
        scope×level×module, поэтому расхождение не может проехать молча.
        """
        if rank_of(level) >= _SEVERITY_PLANE_RANK:
            return True
        return super()._is_gate_open(scope, level, module)

    def _route(self, scope: ScopeName, level: LogLevel, module: str) -> Optional[List[str]]:
        """WARNING/ERROR/CRITICAL → один канал по уровню; остальное — родителю.

        **Ф4.2: это ВСЯ разница между двумя путями эмиссии.** Раньше здесь жил
        полный override ``log()`` — со своей сборкой записи, своим кормлением
        tap'ов, своим enqueue и своим полом. Развилка обходилась в ручное
        зеркалирование каждого улучшения родителя: 0.4 — в двух местах, 0.9 — в
        двух, tap'ы — в двух, а 0.5 забыли, и на ГЛАВНОМ производственном пути
        ошибок пропал ``proc_name``. Теперь общего кода нет в двух копиях,
        потому что второй копии нет.

        Гейт скоупа на этом пути НЕ спрашивается — и это осознанно, а не
        побочно: у ошибки приёмник определяет severity, и порог скоупа
        (у ``SYSTEM`` это ``WARNING``) не должен уметь заглушить ERROR.
        Закреплено характеризационным тестом ``test_severity_path_ignores_scope_gate``.
        """
        channel_name = self._level_to_channel.get(level.value)
        if channel_name is not None:
            return [channel_name]

        if rank_of(level) >= _SEVERITY_PLANE_RANK:
            # Уровень плоскости ошибок, но живого приёмника не осталось (все
            # severity-каналы сняты). Пустой список, а НЕ путь родителя: у
            # скоупов плоскости ошибок приёмников нет по определению (P3), и
            # делегирование туда означало бы «ошибка отклонена гейтом» —
            # то есть тихое исчезновение записи вместо пола.
            #
            # Это не теория: правка P2 (пересборка маршрутов на изменение
            # состава) без этой ветки уронила четыре теста разом, включая оба
            # теста пола. Пустой список ловит ``_write_error_record`` → floor
            # для ERROR/CRITICAL и ``_count_records_without_channels`` для
            # WARNING — обе судьбы видимы наружу.
            return []

        # DEBUG / INFO / неизвестный уровень → scope-based резолв родителя.
        return super()._route(scope, level, module)

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """Логировать исключение с traceback.

        Args:
            exc:               Объект исключения.
            message:           Дополнительный контекст.
            module:            Модуль-источник.
            include_stacktrace: Переопределить глобальный флаг (None → из конфига).
        """
        full_message = f"{message}: {exc}" if message else str(exc)
        use_trace = include_stacktrace if include_stacktrace is not None else self._include_stacktrace
        if use_trace:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                full_message += f"\n{tb}"

        self.error(full_message, module=module)

    def track_error(
        self,
        error: BaseException,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Интеграция с ObservableMixin._track_error. Логирует через log_exception."""
        ctx = context or {}
        message = ctx.get("message", ctx.get("context", ""))
        if isinstance(message, dict):
            message = str(message)
        module = ctx.get("module", "unknown")
        self.log_exception(error, message=message or "", module=module)

    def get_stats(self) -> Dict[str, Any]:
        """Статистика ErrorManager — расширяет LoggerCore.get_stats()."""
        stats = super().get_stats()
        stats["include_stacktrace"] = self._include_stacktrace
        stats["level_routes"] = dict(self._level_to_channel)
        return stats
