# -*- coding: utf-8 -*-
"""
LogStatsChannel — канал вывода метрик в LoggerManager.

При write(data) вызывает logger_manager.performance() с агрегированным снапшотом.
"""

from typing import Any, Dict, List

from ...channel_routing_module.interfaces import IChannel
from ..interfaces import LOG_SOURCE

#: Место, которое резервируется под ГОЛОС потери, чтобы обещание «строка не длиннее
#: предела» держалось вместе с ним, а не вопреки ему. Сам голос — около 60 байт
#: (``… опущено 234 из 306 метрик, предел 2048 байт``); запас взят на длинные числа.
_VOICE_RESERVE_BYTES = 96

#: Предел строки снапшота по умолчанию, байт. Живёт ЗДЕСЬ и импортируется схемой
#: конфига — иначе число стояло бы в двух местах, и тест, проверяющий одно из них,
#: молча сторожил бы не ту позицию.
DEFAULT_LOG_LINE_MAX_BYTES = 2048


class LogStatsChannel(IChannel):
    """Канал записи метрик в лог через LoggerManager."""

    def __init__(
        self,
        logger_manager: Any,
        level: str = "INFO",
        name: str = "log_stats",
        max_bytes: int = DEFAULT_LOG_LINE_MAX_BYTES,
    ) -> None:
        """
        Args:
            logger_manager: LoggerManager для записи
            level: Уровень логирования (INFO, DEBUG, ...)
            name: Имя канала
            max_bytes: предел объёма ОДНОЙ строки снапшота, байт; ``0`` — без предела
        """
        self._logger = logger_manager
        self._level_str = level.upper()
        self._name = name
        self._max_bytes = max_bytes

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "log"

    @property
    def level(self) -> str:
        """Уровень, с которым канал ПИШЕТ сейчас — для readback'а плоскости (B1).

        Читается у живого канала, а не из конфига: после ``sink.enable`` канал
        пересобирается своим сборщиком, и единственная надёжная копия уровня —
        та, что у него в руках.
        """
        return self._level_str

    @property
    def max_bytes(self) -> int:
        """Предел, с которым канал РЕЖЕТ сейчас — для readback'а плоскости.

        Читается у живого канала по той же причине, что и ``level``: после
        ``sink.enable`` и после ``config.reload`` канал пересобирается своим
        сборщиком, и единственная надёжная копия предела — та, что у него в руках.
        Пересчёт из конфига дал бы то же число и при несработавшей пересборке.
        """
        return self._max_bytes

    def _format_snapshot(self, metrics: List[Any], total: int, ts: float) -> str:
        """Собрать строку снапшота, не длиннее ``max_bytes`` — с голосом о потере.

        **Зачем предел.** Непустой снапшот дампил ВЕСЬ список метрик питоновским
        ``repr`` в одну строку: по 416 живым строкам из ``logs_live`` медиана 2582,
        максимум 53 900 байт. Это давало 2.6–5.5 МиБ/ч на восьми процессах, то есть
        одни только снапшоты перекрывали гейт этапа «фон ≤ ~2 МиБ/ч» (задача 3.4).
        При пределе 2048 потолок — 1.24 МиБ/ч, и он держится **в насыщении**, а не
        в среднем по историческому окну: длина строки ограничена сверху.

        **Потеря настоящая, поэтому с голосом.** Файловый приёмник (``file_stats``)
        поднимается только когда лог-канала нет, так что вторым носителем этих чисел
        он НЕ является: опущенные метрики в этом такте не видит никто. Сколько именно
        опущено и из скольких — сказано в самой записи; молчаливое усечение было бы
        ровно тем «следствием без причины», ради которого предел и делался.

        **Предел считается по всей строке**, включая заголовок и голос, — иначе
        «не длиннее 2048» было бы неправдой ровно на длину голоса. Байты, а не
        символы: имена метрик бывают кириллическими.

        ``count`` в заголовке — ПОЛНОЕ число метрик в окне, не число уместившихся.
        По нему снаружи судят о живости окна (``probe_b3_shutdown_order_live``
        считает вхождения маркера, S4), и арифметика «сколько метрик было» не должна
        меняться от того, влезли они в строку или нет.
        """
        head = f"metrics snapshot (ts={ts:.0f}, count={total}): "
        if self._max_bytes <= 0:
            return f"{head}{metrics}"

        budget = self._max_bytes - len(head.encode("utf-8")) - _VOICE_RESERVE_BYTES
        pieces: List[str] = []
        used = 2  # скобки списка
        for rec in metrics:
            piece = repr(rec)
            cost = len(piece.encode("utf-8")) + (2 if pieces else 0)  # ", "
            if used + cost > budget:
                break
            pieces.append(piece)
            used += cost

        if len(pieces) == len(metrics):
            return f"{head}{metrics}"

        dropped = len(metrics) - len(pieces)
        body = "[" + ", ".join(pieces) + "]"
        return f"{head}{body} … опущено {dropped} из {len(metrics)} метрик, предел {self._max_bytes} байт"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Записать снапшот метрик в лог."""
        try:
            if not self._logger:
                return {"status": "error", "error": "LoggerManager not set", "channel": self.name}

            metrics = data.get("metrics", [])
            total = data.get("total_count", 0)
            ts = data.get("timestamp", 0)

            msg = self._format_snapshot(metrics, total, ts)

            # LoggerManager.performance(level, message, module, **extra)
            from ...logger_module.core.log_config import LogLevel

            log_level = getattr(LogLevel, self._level_str, LogLevel.INFO)
            self._logger.performance(log_level, msg, module=LOG_SOURCE)

            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        """Закрыть канал (no-op для лога)."""
        pass

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.channel_type,
            "level": self._level_str,
            "active": True,
        }
