# -*- coding: utf-8 -*-
"""Авторские hazard-тесты канонической свёртки пути писателя (Ф1 «порта наблюдений»).

**Что может сломаться именно в ЭТОМ механизме.** ``_is_tracked`` был чистым
``endswith`` по суффиксу — операция без состояния и без знания о раскладке
дерева. Теперь у него есть ВТОРАЯ попытка: путь вида
``…state.plugins.<писатель>.<имя>`` сворачивается в ``…state.<имя>`` и суффикс
проверяется по свёртке. Опасное всё связано с тем, что свёртка — это угадывание
раскладки по позициям сегментов:

1. *Слишком широкий матч.* Узел ``plugins`` в дереве НЕ ОДИН:
   ``processes.<P>.config.plugins``, ``processes.<P>.plugins.<плагин>.io_peek``,
   корневой каталог ``plugins``. Свёртка «есть где-то сегмент plugins» сложила бы
   чужие пути в несуществующие имена метрик и завела бы кольца истории на
   конфиг. Поэтому проверяются ПОЗИЦИИ ``state``/``plugins`` от хвоста, и здесь
   стоят тесты на каждого из трёх однофамильцев.
2. *Слишком узкий матч.* Обратная ошибка: путь настоящей плагинной метрики не
   попадает в кольцо, и спарклайн GUI молча пустеет. Немой отказ — история
   просто не копится, никто не жалуется.
3. *Ключ кольца.* Свёртка нужна ТОЛЬКО для решения «трекать ли»; писать кольцо
   обязано по ПОЛНОМУ пути. Свернёшь и ключ — два писателя с одноимённой
   метрикой сольются в один буфер, и спарклайн покажет чересполосицу двух рядов
   как один. Это ровно тот класс, который хоронит вся фаза, поэтому у него два
   теста: раздельность колец и неприкосновенность агрегата.
4. *Короткие и вырожденные пути.* ``state.plugins.x`` (нет листа), голое
   ``plugins.fps``, пустая строка — арифметика по индексам ``[-4]``/``[-3]`` на
   них обязана не бросать IndexError.
"""

from __future__ import annotations

from ..telemetry_read_model import DEFAULT_TRACKED_SUFFIXES, TelemetryReadModel


def _model(**kw) -> TelemetryReadModel:
    return TelemetryReadModel(**kw)


class TestPluginPathsGetHistory:
    def test_plugin_path_of_a_tracked_metric_accumulates(self) -> None:
        m = _model()
        path = "processes.cam.state.plugins.capture.fps"
        m.ingest(path, 10.0)
        m.ingest(path, 20.0)
        assert [v for _ts, v in m.history(path)] == [10.0, 20.0]

    def test_flat_aggregate_still_accumulates(self) -> None:
        """Регресс-якорь: старая форма не потерялась при добавлении новой."""
        m = _model()
        path = "processes.cam.state.fps"
        m.ingest(path, 10.0)
        m.ingest(path, 20.0)
        assert [v for _ts, v in m.history(path)] == [10.0, 20.0]

    def test_every_default_suffix_of_the_state_family_works_in_plugin_form(self) -> None:
        """Все ``.state.*``-суффиксы дефолта, а не только ``fps``.

        Набор берётся из ``DEFAULT_TRACKED_SUFFIXES``, но ожидание — литеральное
        (``[1.0, 2.0]`` на каждый), и суффиксы фильтруются по форме ``.state.``:
        per-worker суффиксы (``.effective_hz``) под писателя не сворачиваются и
        ловятся прямым матчем — им отдельный тест ниже.
        """
        state_suffixes = [s for s in DEFAULT_TRACKED_SUFFIXES if s.startswith(".state.")]
        assert state_suffixes, "дефолтный набор потерял .state.*-суффиксы — тест ослеп"
        for suffix in state_suffixes:
            metric = suffix.rsplit(".", 1)[-1]
            m = _model()
            path = f"processes.cam.state.plugins.probe.{metric}"
            m.ingest(path, 1.0)
            m.ingest(path, 2.0)
            assert [v for _ts, v in m.history(path)] == [1.0, 2.0], f"суффикс {suffix} не сработал"

    def test_per_worker_suffix_is_matched_directly_not_by_folding(self) -> None:
        """``.effective_hz`` ловится прямым суффиксом — свёртка ему не нужна и не мешает."""
        m = _model()
        path = "processes.cam.workers.w1.effective_hz"
        m.ingest(path, 5.0)
        m.ingest(path, 6.0)
        assert [v for _ts, v in m.history(path)] == [5.0, 6.0]

    def test_unknown_metric_name_under_a_writer_is_not_tracked(self) -> None:
        """Свёртка не делает трекаемым ИМЯ, которого нет в наборе.

        Пара к тестам выше: без неё «плагинные пути копятся» было бы неотличимо
        от «копится всё подряд», и кольца завелись бы на каждый лист дерева.
        """
        m = _model()
        path = "processes.cam.state.plugins.capture.drops"
        m.ingest(path, 1)
        m.ingest(path, 2)
        assert m.history(path) == []


class TestFoldingIsNarrow:
    def test_config_plugins_subtree_is_not_folded(self) -> None:
        """``processes.<P>.config.plugins.<x>.fps`` — однофамилец, а не метрика."""
        m = _model()
        path = "processes.cam.config.plugins.capture.fps"
        m.ingest(path, 1.0)
        m.ingest(path, 2.0)
        assert m.history(path) == []

    def test_runtime_io_peek_plugins_node_is_not_folded(self) -> None:
        """``processes.<P>.plugins.<плагин>.fps`` — узел io_peek, между ним и ``state`` разницы в один сегмент."""
        m = _model()
        path = "processes.cam.plugins.capture.fps"
        m.ingest(path, 1.0)
        m.ingest(path, 2.0)
        assert m.history(path) == []

    def test_root_plugins_catalog_is_not_folded(self) -> None:
        m = _model()
        path = "plugins.catalog.fps"
        m.ingest(path, 1.0)
        m.ingest(path, 2.0)
        assert m.history(path) == []

    def test_nested_level_under_a_writer_is_not_folded_by_the_state_rule(self) -> None:
        """Глубже писателя свёртка не лезет: ``plugins.<w>.deeper.fps`` не станет ``state.fps``."""
        m = _model()
        path = "processes.cam.state.plugins.capture.deeper.fps"
        m.ingest(path, 1.0)
        m.ingest(path, 2.0)
        assert m.history(path) == []


class TestRingKeyKeepsTheWriter:
    def test_two_writers_of_the_same_metric_keep_separate_rings(self) -> None:
        """Кольцо ключуется ПОЛНЫМ путём: свернёшь ключ — два ряда слипнутся в один."""
        m = _model()
        a = "processes.cam.state.plugins.capture.fps"
        b = "processes.cam.state.plugins.color_mask.fps"
        m.ingest(a, 10.0)
        m.ingest(b, 90.0)
        m.ingest(a, 11.0)
        m.ingest(b, 91.0)
        assert [v for _ts, v in m.history(a)] == [10.0, 11.0]
        assert [v for _ts, v in m.history(b)] == [90.0, 91.0]

    def test_the_flat_aggregate_ring_stays_untouched_by_writers(self) -> None:
        """Пара к предыдущему: писатель не подмешивается в кольцо агрегата ``state.fps``.

        Без этого теста «раздельные кольца» доказано только между писателями, а
        свёртка целится именно в адрес агрегата — самое вероятное место слипания.
        """
        m = _model()
        flat = "processes.cam.state.fps"
        writer = "processes.cam.state.plugins.capture.fps"
        m.ingest(flat, 1.0)
        m.ingest(writer, 100.0)
        m.ingest(flat, 2.0)
        assert [v for _ts, v in m.history(flat)] == [1.0, 2.0]
        assert [v for _ts, v in m.history(writer)] == [100.0]


class TestDegeneratePaths:
    def test_short_paths_do_not_raise(self) -> None:
        """Индексы ``[-4]``/``[-3]`` на коротких путях: отсутствие исключения — тоже свойство."""
        m = _model()
        for path in ("", "fps", "state.fps", "state.plugins.fps", ".state.fps"):
            m.ingest(path, 1.0)  # не должно бросать
        assert m.get("state.plugins.fps") == 1.0

    def test_empty_tracked_set_tracks_nothing_including_plugin_paths(self) -> None:
        """``tracked_suffixes=()`` выключает историю целиком — свёртка не обходит выключатель."""
        m = _model(tracked_suffixes=())
        path = "processes.cam.state.plugins.capture.fps"
        m.ingest(path, 1.0)
        m.ingest(path, 2.0)
        assert m.history(path) == []
        assert m.get(path) == 2.0  # снимок при этом работает

    def test_custom_tracked_suffix_also_works_through_the_folding(self) -> None:
        """Свёртка не зашита на дефолтный набор — потребитель со своим суффиксом её получает."""
        m = _model(tracked_suffixes=(".state.drops",))
        path = "processes.cam.state.plugins.capture.drops"
        m.ingest(path, 1)
        m.ingest(path, 2)
        assert [v for _ts, v in m.history(path)] == [1.0, 2.0]

    def test_purge_of_the_writer_subtree_drops_its_ring(self) -> None:
        """Удаление поддерева писателя чистит и снимок, и кольцо — соседа не задев."""
        m = _model()
        a = "processes.cam.state.plugins.capture.fps"
        b = "processes.cam.state.plugins.color_mask.fps"
        m.ingest(a, 10.0)
        m.ingest(b, 90.0)
        m.ingest("processes.cam.state.plugins.capture", None, deleted=True)
        assert m.get(a) is None
        assert m.history(a) == []
        assert m.get(b) == 90.0
        assert [v for _ts, v in m.history(b)] == [90.0]
