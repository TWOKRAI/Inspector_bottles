# -*- coding: utf-8 -*-
"""Предел объёма строки стат-снапшота (задача 3.4).

Непустой снапшот дампил ВЕСЬ список метрик питоновским ``repr`` в одну строку лога:
по 416 живым строкам из ``logs_live`` медиана 2582, максимум 53 900 байт. Одни только
эти строки давали 2.6–5.5 МиБ/ч на восьми процессах, то есть перекрывали гейт этапа
«фон ≤ ~2 МиБ/ч» независимо от остальных задач.

Здесь сторожатся четыре обещания предела:
1. строка не длиннее предела — целиком, вместе с заголовком и голосом;
2. потеря названа числом (сколько опущено из скольких) — молча резать нельзя;
3. ``count`` в заголовке остаётся ПОЛНЫМ числом метрик окна: по маркеру снаружи судят
   о живости статистики (``probe_b3_shutdown_order_live``), и это число не должно
   зависеть от того, влезли метрики в строку или нет;
4. ручка живая — предел из конфига доезжает до канала, а не подменяется дефолтом.

Числа в тестах намеренно НЕ равны дефолту (2048): тест со значением рядом с дефолтом
проверяет дефолт, а не ручку.
"""

import re
from unittest.mock import MagicMock

from .. import StatsManager
from ..channels.log_stats_channel import DEFAULT_LOG_LINE_MAX_BYTES, LogStatsChannel
from ..configs.stats_config import StatsManagerConfig

_VOICE = re.compile(r"опущено (\d+) из (\d+) метрик, предел (\d+) байт")


def _metrics(n: int, name_prefix: str = "m") -> list:
    """n метрик формы, которую отдаёт ``MetricRecord.aggregate``."""
    return [
        {
            "name": f"{name_prefix}{i:04d}",
            "type": "timing",
            "tags": {"process": "camera_0", "stage": "detect"},
            "count": 17,
            "min": 0.001,
            "max": 0.244,
            "avg": 0.0731,
            "p95": 0.199,
        }
        for i in range(n)
    ]


def _cyrillic_metrics(n: int) -> list:
    """Метрики, у которых кириллица ДОМИНИРУЕТ — байт вдвое больше символов.

    Первая редакция теста ставила кириллицу только в имя, и разница между байтами и
    символами оказывалась меньше резерва под голос: инъекция «считать символы» не
    красила ничего. Тест заявлял свойство, которого не сторожил.
    """
    return [
        {
            "name": f"длительность_обработки_кадра_камеры_{i:04d}",
            "type": "gauge",
            "tags": {"процесс": "камера_ноль", "этап": "поиск_дефектов"},
            "value": 0.0731,
        }
        for i in range(n)
    ]


def _tiny_metrics(n: int) -> list:
    """Мелкие метрики — шаг набора ~45 байт вместо ~190.

    На крупном шаге тело почти никогда не подходит к границе бюджета вплотную, и
    отсутствие резерва под голос остаётся незамеченным. Здесь шаг мелкий, поэтому
    тело упирается в бюджет впритык и голос обязан быть учтён заранее.
    """
    return [{"name": f"c{i}", "type": "counter", "count": i} for i in range(n)]


def _written(logger: MagicMock) -> str:
    """Сообщение, дошедшее до LoggerManager.performance."""
    assert logger.performance.call_count == 1, logger.performance.call_args_list
    return logger.performance.call_args[0][1]


def _snapshot(metrics: list) -> dict:
    return {"timestamp": 1_700_000_000.0, "total_count": len(metrics), "metrics": metrics}


class TestLineFitsTheLimit:
    def test_long_snapshot_is_cut_to_the_limit(self):
        """Строка целиком (заголовок + тело + голос) укладывается в предел."""
        logger = MagicMock()
        ch = LogStatsChannel(logger_manager=logger, max_bytes=700)

        assert ch.write(_snapshot(_metrics(300)))["status"] == "success"

        msg = _written(logger)
        assert len(msg.encode("utf-8")) <= 700, f"строка {len(msg.encode('utf-8'))} байт при пределе 700"

    def test_limit_counts_bytes_not_characters(self):
        """Кириллические имена: предел меряется в байтах UTF-8.

        Хазард механизма: ``len(str)`` дал бы вдвое более длинную запись на кириллице,
        а фон меряется байтами на диске.
        """
        logger = MagicMock()
        metrics = _cyrillic_metrics(300)
        ch = LogStatsChannel(logger_manager=logger, max_bytes=700)

        ch.write(_snapshot(metrics))

        msg = _written(logger)
        assert len(msg.encode("utf-8")) <= 700, f"строка {len(msg.encode('utf-8'))} байт при пределе 700"

        # Страж ФИКСТУРЫ, а не строки: если данные обмелеют до латиницы, разница между
        # символами и байтами исчезнет, и тест продолжит называться «про байты», ничего
        # про них не проверяя. Мерится сама запись — в строке ещё есть ASCII-обвязка
        # (`'name'`, `'type'`, скобки), которая соотношение занижает.
        piece = repr(metrics[0])
        assert len(piece.encode("utf-8")) > 1.4 * len(piece), (
            "данные обмелели — подсчёт в символах прошёл бы незамеченным"
        )

    def test_voice_fits_inside_the_limit_when_body_ends_flush_with_it(self):
        """Тело подходит к бюджету впритык — голос всё равно внутри предела.

        Место под голос вычитается ЗАРАНЕЕ. Иначе строка выходит за предел ровно на
        длину голоса, и обещание «не длиннее max_bytes» неверно именно тогда, когда
        предел работает: на мелких метриках шаг набора ~45 байт, и тело почти всегда
        упирается в границу.
        """
        logger = MagicMock()
        ch = LogStatsChannel(logger_manager=logger, max_bytes=600)

        ch.write(_snapshot(_tiny_metrics(400)))

        msg = _written(logger)
        assert "опущено" in msg, "срез не сработал — тест бессмыслен"
        assert len(msg.encode("utf-8")) <= 600, f"строка {len(msg.encode('utf-8'))} байт при пределе 600"

    def test_short_snapshot_is_untouched(self):
        """Малый снапшот не трогается: ни среза, ни голоса — прежняя строка дословно."""
        logger = MagicMock()
        metrics = _metrics(3)
        ch = LogStatsChannel(logger_manager=logger, max_bytes=700)

        ch.write(_snapshot(metrics))

        msg = _written(logger)
        assert msg == f"metrics snapshot (ts=1700000000, count=3): {metrics}"
        assert "опущено" not in msg

    def test_zero_means_no_limit(self):
        """``0`` снимает предел — для отладки нужен полный дамп."""
        logger = MagicMock()
        metrics = _metrics(300)
        ch = LogStatsChannel(logger_manager=logger, max_bytes=0)

        ch.write(_snapshot(metrics))

        msg = _written(logger)
        assert msg.endswith(f"{metrics}")
        assert len(msg.encode("utf-8")) > 10_000

    def test_single_metric_larger_than_budget_does_not_crash(self):
        """Одна метрика не влезает целиком: тело пустое, но запись есть и предел цел.

        Граница механизма: «сохранено 0» — законный исход, а не повод уронить канал
        или выпустить строку сверх предела.
        """
        logger = MagicMock()
        ch = LogStatsChannel(logger_manager=logger, max_bytes=200)

        assert ch.write(_snapshot(_metrics(1)))["status"] == "success"

        msg = _written(logger)
        assert len(msg.encode("utf-8")) <= 200
        assert _VOICE.search(msg).groups()[:2] == ("1", "1")


class TestLossHasAVoice:
    def test_voice_matches_what_actually_survived(self):
        """Число в голосе сходится с тем, сколько имён реально осталось в строке.

        Считается арифметикой по самой строке, а не берётся из кода под тестом:
        иначе утверждение согласилось бы с любым ответом, включая «опущено 0».
        """
        logger = MagicMock()
        metrics = _metrics(120)
        ch = LogStatsChannel(logger_manager=logger, max_bytes=900)

        ch.write(_snapshot(metrics))

        msg = _written(logger)
        dropped, total, limit = (int(g) for g in _VOICE.search(msg).groups())
        survived = sum(1 for rec in metrics if f"'{rec['name']}'" in msg)

        assert total == 120
        assert limit == 900
        assert dropped == 120 - survived, f"голос обещает {dropped} опущенных, в строке осталось {survived} из 120"
        assert 0 < survived < 120, "тест бессмыслен, если срез не сработал или срезал всё"

    def test_header_count_stays_full_after_the_cut(self):
        """``count`` в заголовке — полное число метрик окна, а не число уместившихся."""
        logger = MagicMock()
        ch = LogStatsChannel(logger_manager=logger, max_bytes=900)

        ch.write(_snapshot(_metrics(120)))

        msg = _written(logger)
        assert msg.startswith("metrics snapshot (ts=1700000000, count=120): ")

    def test_marker_prefix_survives_the_cut(self):
        """Потребители снаружи считают вхождения маркера — префикс обязан уцелеть.

        ``probe_b3_shutdown_order_live`` судит по нему, что статистика дожила до
        финального сброса; ``test_performance_plane_own_file`` — что плоскость
        физически легла в свой файл.
        """
        logger = MagicMock()
        ch = LogStatsChannel(logger_manager=logger, max_bytes=300)

        ch.write(_snapshot(_metrics(300)))

        assert "metrics snapshot" in _written(logger)


class TestKnobIsAlive:
    def test_manager_passes_the_configured_limit_to_the_channel(self):
        """Предел из конфига доезжает до канала — проверяется длиной живой записи.

        Хазард: ручка, объявленная в схеме и не прочитанная сборщиком канала,
        выглядит рабочей в конфиге и не действует ни на байт.
        """
        logger = MagicMock()
        mgr = StatsManager(
            manager_name="LimitStats",
            config={"enable_logging": True, "log_line_max_bytes": 512, "channels": {}},
            managers={"logger": logger},
        )
        assert mgr.initialize() is True
        try:
            channel = mgr._channel_registry.get("log_stats")
            assert channel is not None, "лог-канал не поднялся — тест не о том"
            logger.performance.reset_mock()  # инициализация могла писать сама

            channel.write(_snapshot(_metrics(300)))

            assert len(_written(logger).encode("utf-8")) <= 512
        finally:
            mgr.shutdown()

    def test_two_different_limits_give_two_different_lengths(self):
        """Пара значений ручки: одно значение не отличает предел от совпавшей константы."""
        lengths = {}
        for limit in (600, 1500):
            logger = MagicMock()
            LogStatsChannel(logger_manager=logger, max_bytes=limit).write(_snapshot(_metrics(300)))
            lengths[limit] = len(_written(logger).encode("utf-8"))

        assert lengths[600] < lengths[1500] <= 1500

    def test_default_lives_in_one_place(self):
        """Схема и сигнатура канала берут дефолт из ОДНОЙ позиции.

        Два независимых литерала с одинаковым значением расходятся молча, и тест,
        проверяющий один из них, сторожит не ту позицию.
        """
        assert StatsManagerConfig.model_fields["log_line_max_bytes"].default is DEFAULT_LOG_LINE_MAX_BYTES

        logger = MagicMock()
        LogStatsChannel(logger_manager=logger).write(_snapshot(_metrics(300)))
        assert len(_written(logger).encode("utf-8")) <= DEFAULT_LOG_LINE_MAX_BYTES


class TestLimitIsReadableFromOutside:
    """Предел виден в readback'е — иначе его применение нечем подтвердить.

    Живой прогон до этой правки вернул ``verdict=failed`` на всех восьми процессах:
    ключа не было ни в фасаде, ни в readback'е, и ``config_reload_verified`` не мог
    отличить «применено» от «проглочено». Ручка, которую нельзя прочитать, неотличима
    от неприменённой.
    """

    def _manager(self, logger: MagicMock, limit: int) -> StatsManager:
        mgr = StatsManager(
            manager_name="ReadbackStats",
            config={"enable_logging": True, "log_line_max_bytes": limit, "channels": {}},
            managers={"logger": logger},
        )
        assert mgr.initialize() is True
        return mgr

    def test_readback_reports_the_live_limit(self):
        mgr = self._manager(MagicMock(), 777)
        try:
            assert mgr.observability_readback()["log_line_max_bytes"] == 777
        finally:
            mgr.shutdown()

    def test_readback_follows_a_reconfigure(self):
        """После пересборки readback показывает НОВЫЙ предел, а не запомненный.

        Читать полагается у живого канала: пересчёт из конфига дал бы верное число
        и при полностью несработавшей пересборке — эхо запроса вместо факта.
        """
        mgr = self._manager(MagicMock(), 777)
        try:
            mgr.reconfigure({"enable_logging": True, "log_line_max_bytes": 333, "channels": {}})
            assert mgr.observability_readback()["log_line_max_bytes"] == 333
        finally:
            mgr.shutdown()

    def test_readback_reports_the_channel_not_the_config(self):
        """Когда конфиг и живой канал расходятся, readback показывает КАНАЛ.

        Соседний тест (пересборка) этого не отличает: reconfigure обновляет и конфиг,
        и канал, поэтому оба источника дают один ответ и чтение «не оттуда» проходит
        незамеченным. Здесь расхождение создано намеренно — иначе readback остался бы
        эхом запроса, а не фактом.
        """
        mgr = self._manager(MagicMock(), 777)
        try:
            channel = mgr._channel_registry.get("log_stats")
            channel._max_bytes = 333  # канал ушёл от конфига: конфиг всё ещё говорит 777

            assert mgr.observability_readback()["log_line_max_bytes"] == 333
        finally:
            mgr.shutdown()
