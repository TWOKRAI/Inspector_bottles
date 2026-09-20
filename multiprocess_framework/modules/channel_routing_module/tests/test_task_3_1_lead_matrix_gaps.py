# -*- coding: utf-8 -*-
"""Сторожа, заведённые матрицей инъекций ведущего (Task 3.1, 2026-09-05).

Файл существует отдельно от приёмочного набора слепого тестера и от hazard-набора
автора **ради происхождения**: каждый тест здесь появился потому, что заплата,
ломающая заявленное свойство, не убила НИ ОДНОГО теста. Ноль красных в матрице —
это не «свойство прочное», это «свойство никем не сторожится», и различить их
можно только назвав, откуда тест взялся.

Две такие позиции у Task 3.1:

* **И15** — заплата «``search()`` молча игнорирует фильтр ``metric``»: 0 красных.
  Набор фильтров общий у ленты и поиска (``_filter_clauses``), и это правильно, но
  проверяла его только лента. Дефект был бы ровно того класса, ради которого общий
  набор и заводился: «фильтр сузил ленту, но не сузил поиск» читалось бы как
  дефект поиска, а не как потерянное условие.
* **И16** — заплата «``skipped_origin`` теряет значение маркера и едет ``True``»:
  0 красных. Докстринг ``StoreTapChannel.write`` утверждает, что значением едет
  ИМЕННО маркер («маркеров у поля ``origin`` уже два, и „пропущено по origin“ без
  имени пришлось бы доискивать в исходнике»), а приёмочный тест проверял только
  присутствие ключа. Утверждение без сторожа переживает свой предмет.
"""

from __future__ import annotations

import pytest

from ..observability.observability_store import ObservabilityStore
from ..observability.store_tap import ORIGIN_FIELD, ORIGIN_STATS_SNAPSHOT, StoreTapChannel


def _log_row(message: str, ts: float, module: str) -> dict:
    """Hub-запись лога — ровно та форма, что приходит в ``append_records``."""
    return {"kind": "log", "module": module, "ts": ts, "severity": "info", "message": message}


def _observation_row(writer: str, metric: str, value: float, ts: float) -> dict:
    return {"kind": "observation", "module": "camera_0", "ts": ts, "writer": writer, "metric": metric, "value": value}


class TestSearchNarrowsByMetricToo:
    """И15: фильтр ``metric`` обязан сужать И поиск, а не только ленту."""

    @pytest.fixture()
    def store(self, tmp_path):
        st = ObservabilityStore(str(tmp_path / "obs.db"))
        if not st.search_available:
            st.close()
            pytest.skip(f"FTS5 недоступен в этой сборке SQLite: {st.search_unavailable_reason}")
        st.append_records(
            [
                _observation_row("capture", "drops", 1, 1.0),
                _observation_row("capture", "frames", 2, 2.0),
                _log_row("capture drops and frames both mention capture", 3.0, "camera_0"),
            ]
        )
        yield st
        st.close()

    def test_metric_filter_narrows_the_search_not_only_the_feed(self, store) -> None:
        """Сломается: если ``search`` перестанет передавать ``metric`` в общий набор.

        Пара «подтверждающий результат + контроль» обязательна: один вызов с
        фильтром и один без него на ОДНОМ И ТОМ ЖЕ тексте. Иначе «нашлась одна
        строка» неотличимо от «текст встречается один раз».
        """
        wide = store.search("capture")
        narrow = store.search("capture", metric="capture.drops")

        assert len(wide) >= 3, f"КОНТРОЛЬ: без фильтра текст 'capture' обязан найтись >=3 раз, нашлось {len(wide)}"
        assert [r["metric"] for r in narrow] == ["capture.drops"], (
            f"фильтр metric не сузил ПОИСК (сузил бы ленту): {[r.get('metric') for r in narrow]}"
        )


class TestSkippedOriginCarriesTheMarkerNotABareTrue:
    """И16: значение ``skipped_origin`` — сам маркер, а не ``True``."""

    def test_value_is_the_marker_so_the_reader_knows_which_origin_was_skipped(self, tmp_path) -> None:
        """Сломается: если значением поедет ``True`` или любой другой флаг.

        Проверяется РАВЕНСТВО маркеру, а не истинность: ``True`` тоже истинно,
        и проверка «ключ есть и он truthy» пропустила бы подмену целиком. У поля
        ``origin`` маркеров уже два (``error_manager`` и ``stats_snapshot``), и
        различить их по возврату — весь смысл ключа.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="t", process="p")

        result = tap.write(
            {
                "timestamp": 1.0,
                "level": "INFO",
                "module": "stats",
                "message": "metrics snapshot (count=1): fps",
                "extra": {ORIGIN_FIELD: ORIGIN_STATS_SNAPSHOT},
            }
        )

        assert result["skipped_origin"] == ORIGIN_STATS_SNAPSHOT, (
            f"значением обязан ехать сам маркер, а не флаг: {result.get('skipped_origin')!r}"
        )
        # Дожать очередь ОБЯЗАТЕЛЬНО (Task 3.3): без этого «ноль строк» ниже
        # означал бы «очередь ещё не слита», а не «строка пропущена».
        tap.flush(timeout=2.0)
        assert store.count() == 0, "пропущенная строка не имеет права оказаться в сторе"
        store.close()
