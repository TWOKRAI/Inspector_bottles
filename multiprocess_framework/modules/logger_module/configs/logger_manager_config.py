# -*- coding: utf-8 -*-
"""
LoggerManagerConfig — SchemaBase / ChannelRoutingConfig для LoggerManager.

Каналы, scopes и modules — отдельные сущности (как в прототипе managers_schema_lite).
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional

from pydantic import Field, field_validator

from ...channel_routing_module import ChannelRoutingConfig
from ...channel_routing_module.buffers.batch_buffer import (
    DEFAULT_MAX_PENDING,
    DEFAULT_OVERFLOW_POLICY,
    validate_overflow_policy,
)
from ...channel_routing_module.levels import LEVEL_ORDER, LEVEL_RANKS, UNKNOWN_RANK
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..log_enums import LogLevel

_STD_FMT = "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s"
_FILE_MAX = 10 * 1024 * 1024

#: Порядок уровней — из общего дома трёх плоскостей, а не своей копией.
#: Своя копия здесь уже была: пока она жила рядом, гейт логгера и severity-путь
#: ошибок сравнивали уровни по двум разным кортежам, и расхождение было бы
#: молчаливым (тот же класс, что _RETENTION_STAT_KEYS в Ф0.7).
_LEVEL_ORDER = LEVEL_ORDER


class LoggerChannelSchema(SchemaBase):
    """Описание одного канала логирования."""

    name: str = ""
    type: str = "file"
    enabled: bool = True
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    max_size: int = 10 * 1024 * 1024
    backup_count: int = 5
    rotate: bool = True
    file_path: Optional[str] = None
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    # Только для type="memory": сколько ЗАПИСЕЙ держит кольцо в памяти процесса.
    # Отдельным полем, а не переиспользованием max_size: там байты, и 10 МБ,
    # прочитанные как число записей, дали бы кольцо на 10 миллионов элементов.
    capacity: Optional[int] = None


class LoggerScopeSchema(SchemaBase):
    """Скоуп логирования (ключи SYSTEM, BUSINESS, …)."""

    enabled: bool = True
    min_level: str = _LEVEL_ORDER[1]  # INFO
    channels: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)

    @field_validator("min_level")
    @classmethod
    def _normalize_min_level(cls, value: str) -> str:
        """Ф1.1: порог приводится к канону ОДИН раз — на границе конфига.

        Прежняя реализация звала ``self.min_level.upper()`` на КАЖДОЙ записи,
        то есть аллоцировала строку ради решения «писать или нет». Нормализация
        здесь снимает эту цену навсегда и заодно делает ``min_level`` в
        ``model_dump`` каноничным.

        Валидатор поля, а не хранение производной рядом: приватный атрибут
        Pydantic-модели читается через ``__getattr__``, и замер показал **921 нс
        против 47 нс** у обычного поля — «оптимизация» через ``PrivateAttr``
        делала гейт впятеро ДОРОЖЕ прежнего. Поймано бенчем Ф1.6, а не глазом.
        """
        return value.upper() if isinstance(value, str) else value

    def should_log(self, level: LogLevel, module: str) -> bool:
        """Пройдёт ли запись гейт скоупа. Горячий путь — без аллокаций.

        Незнакомый уровень (или незнакомый ``min_level``) ПРОПУСКАЕТ запись
        вместе с фильтром модулей — ровно как прежняя реализация, где
        ``ValueError`` из ``index()`` возвращал ``True`` до проверки модулей.
        Это характеризовано тестом: «тише DEBUG» из-за опечатки в имени уровня
        было бы тихой потерей.

        Что осталось на пути решения: два обращения к полям модели, два
        словарных лукапа и сравнение int. Ни линейного поиска по кортежу
        (``LEVEL_ORDER.index``), ни ``.upper()``.
        """
        if not self.enabled:
            return False
        min_rank = LEVEL_RANKS.get(self.min_level, UNKNOWN_RANK)
        if min_rank == UNKNOWN_RANK:
            return True
        rank = LEVEL_RANKS.get(level.value, UNKNOWN_RANK)
        if rank == UNKNOWN_RANK:
            return True
        if rank < min_rank:
            return False
        # Список, а не frozenset: он почти всегда пуст, а его материализация в
        # множество жила бы в приватном атрибуте — то есть на дорогом пути.
        modules = self.modules
        if modules and module not in modules:
            return False
        return True


class LoggerModuleSchema(SchemaBase):
    """Per-module file logging (router_messages, processor, …)."""

    enabled: bool = True
    file_path: Optional[str] = None
    min_level: str = "DEBUG"
    max_size: Optional[int] = None
    backup_count: Optional[int] = None
    rotate: bool = True


@register_schema("LoggerManagerConfig")
class LoggerManagerConfig(ChannelRoutingConfig):
    """Конфигурация LoggerManager: каналы, scopes, modules."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "LoggerManager"

    app_name: str = "unknown_app"
    default_level: str = "INFO"
    log_directory: Annotated[
        Optional[str],
        FieldMeta(
            "Корень для относительных file_path каналов и modules. "
            "None — каталог из MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR или системный temp "
            "(не текущий каталог пакета)."
        ),
    ] = None
    enable_batching: bool = True
    batch_size: int = 100
    batch_interval: float = 1.0
    batch_max_pending: Annotated[
        int,
        FieldMeta(
            "Потолок неотправленных записей НА КАНАЛ. Медленный сток без потолка "
            "съедает память тихо (Ф0.3). 0 — без потолка."
        ),
    ] = DEFAULT_MAX_PENDING
    batch_overflow_policy: Annotated[
        str,
        FieldMeta("Что терять при переполнении: drop_oldest (кольцо) | drop_newest"),
    ] = DEFAULT_OVERFLOW_POLICY

    # Ф0.7. Ротация ограничивает каждый файл, но не их число: живой замер дал
    # 730 файлов / 291 МБ и ни одного удаления за 82 дня. Обе политики
    # выключены по умолчанию — механизм, который сам решает что удалить, не
    # включается молча.
    retention_days: Annotated[
        int,
        FieldMeta("Удалять логи старше N суток (0 — выключено)", min=0, max=3650),
    ] = 0
    retention_total_mb: Annotated[
        int,
        FieldMeta("Потолок суммарного веса каталога логов, МБ (0 — выключено)", min=0, max=1_000_000),
    ] = 0
    compress_rotated: Annotated[
        bool,
        FieldMeta("Сжимать ротированные бэкапы (foo.log.1 → foo.log.1.gz)"),
    ] = False

    modules: Annotated[
        Dict[str, LoggerModuleSchema],
        FieldMeta("Per-module файлы"),
    ] = {
        "router_messages": LoggerModuleSchema(
            enabled=True,
            file_path="messages.log",
            # INFO, не DEBUG: на DEBUG router_messages писал маршрут КАЖДОГО кадра
            # (data X -> [Y]) → messages.log распухал на ~МБ/сек. Для отладки роутинга
            # временно вернуть "DEBUG".
            min_level="INFO",
        ),
        "database": LoggerModuleSchema(
            enabled=True,
            file_path="database.log",
            min_level="INFO",
        ),
        "processor": LoggerModuleSchema(
            enabled=True,
            file_path="processor.log",
            min_level="INFO",
        ),
        "processor_frames": LoggerModuleSchema(
            enabled=True,
            file_path="frames.log",
            min_level="DEBUG",
            rotate=False,
        ),
        "camera": LoggerModuleSchema(
            enabled=True,
            file_path="camera.log",
            min_level="INFO",
        ),
        "renderer": LoggerModuleSchema(
            enabled=True,
            file_path="renderer.log",
            min_level="INFO",
        ),
        "robot": LoggerModuleSchema(
            enabled=True,
            file_path="robot.log",
            min_level="INFO",
        ),
        "gui": LoggerModuleSchema(
            enabled=True,
            file_path="gui.log",
            min_level="INFO",
        ),
        # trace — отдельный файл для диагностики cross-layer цепочек.
        # Логи с module="trace" уходят сюда (плюс в scope-каналы:
        # system_file/messages_file/console).
        "trace": LoggerModuleSchema(
            enabled=True,
            file_path="trace.log",
            min_level="DEBUG",
        ),
    }

    channels: Annotated[
        Dict[str, LoggerChannelSchema],
        FieldMeta("Каналы: имя → параметры"),
    ] = {
        "system_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="system.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
        ),
        "messages_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="messages.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
        ),
        "console": LoggerChannelSchema(
            type="console",
            enabled=True,
            format=_STD_FMT,
        ),
    }

    scopes: Annotated[
        Dict[str, LoggerScopeSchema],
        FieldMeta("Скоупы: SYSTEM, BUSINESS, …"),
    ] = {
        "SYSTEM": LoggerScopeSchema(
            enabled=True,
            min_level="WARNING",
            channels=["console", "system_file"],
        ),
        "BUSINESS": LoggerScopeSchema(
            enabled=True,
            min_level=_LEVEL_ORDER[1],
            # console НЕ подключён к BUSINESS: пер-кадровые INFO-логи воркеров
            # уходят только в файлы (system_file/messages_file), а не засоряют
            # терминал. В stdout остаётся лишь SYSTEM WARNING+ через свой scope.
            channels=["system_file", "messages_file"],
        ),
        "PERFORMANCE": LoggerScopeSchema(
            enabled=True,
            min_level=_LEVEL_ORDER[1],
            channels=["system_file"],
        ),
        # DEBUG-scope по умолчанию ВЫКЛЮЧЕН: на DEBUG в system_file лился пер-кадровый
        # firehose (периодический TRACE-лог PipelineExecutor — снят в Ф7 G.1,
        # channel_dispatcher "no route" на каждый кадр) → ~100 МБ/мин, постоянная
        # ротация затирала историю. INFO+ продолжают писаться в файлы через
        # SYSTEM/BUSINESS. Для отладки временно enabled=True.
        "DEBUG": LoggerScopeSchema(
            enabled=False,
            min_level="DEBUG",
            channels=["system_file"],
        ),
    }

    @field_validator("batch_overflow_policy")
    @classmethod
    def _check_overflow_policy(cls, value: str) -> str:
        """Отказ на ГРАНИЦЕ конфига, а не в конструкторе буфера.

        Иначе опечатка всплывала бы посреди ``reconfigure``: старый буфер уже
        остановлен, каналы пересозданы, ``self.config`` подменён — и менеджер
        оставался бы в полуприменённом состоянии с молча выключенным батчингом.
        """
        return validate_overflow_policy(value)
