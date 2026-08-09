# -*- coding: utf-8 -*-
"""Ф5.2, пункт 5: у истории появился предел. До этого его не было вовсе.

Пока в стор писал один error-путь, безлимитная таблица сходила с рук. С приходом
лог-плоскости (порог `observability.history.level`) она стала бы инцидентом 645 МБ,
повторённым в SQLite, — поэтому ретеншен здесь условие задачи, а не её опция.

Часы передаются параметром: глобальный патч часов даёт флейк, а зависимость,
переданная явно, проверяется литералом.
"""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityStore


def _record(ts: float, message: str = "строка", kind: str = "log"):
    return {
        "kind": kind,
        "process": "camera_0",
        "module": "worker_module",
        "ts": ts,
        "severity": "info",
        "message": message,
        "context": {},
    }


def _store(tmp_path, count: int = 0, *, first_ts: float = 1000.0, step: float = 1.0):
    store = ObservabilityStore(str(tmp_path / "obs.db"))
    if count:
        store.append_records([_record(first_ts + i * step, f"строка-{i}") for i in range(count)])
    return store


class TestRowLimit:
    def test_keeps_the_newest_and_drops_the_rest(self, tmp_path) -> None:
        store = _store(tmp_path, 10)
        try:
            report = store.purge(max_rows=4)

            assert report["by_rows"] == 6
            assert report["remaining"] == 4
            left = sorted(row["message"] for row in store.list_records())
            assert left == ["строка-6", "строка-7", "строка-8", "строка-9"]
        finally:
            store.close()

    def test_limit_larger_than_the_table_deletes_nothing(self, tmp_path) -> None:
        store = _store(tmp_path, 3)
        try:
            report = store.purge(max_rows=100)
            assert (report["by_age"], report["by_rows"], report["remaining"]) == (0, 0, 3)
        finally:
            store.close()

    def test_deleted_pages_are_returned_to_the_os_not_just_freed(self, tmp_path) -> None:
        """Живая находка 2026-08-09: ретеншен резал СТРОКИ, но не БАЙТЫ.

        На стенде: 2597 свободных страниц из 2988 (87 % файла), 11.67 МиБ при 3470
        живых строках. Формально предел держался — файл не рос выше пика, — но
        «объём ограничен» звучало шире, чем было правдой.

        Проверяется наблюдаемое следствие: после среза свободных страниц не
        накапливается. Без ``auto_vacuum=INCREMENTAL`` + ``incremental_vacuum``
        их было бы много.
        """
        store = _store(tmp_path, 400)
        try:
            report = store.purge(max_rows=10)

            assert report["by_rows"] == 390
            assert report["free_pages"] == 0, f"освободившиеся страницы остались в файле: {report}"
        finally:
            store.close()

    def test_zero_means_no_limit_not_delete_everything(self, tmp_path) -> None:
        """Мусор в конфиге не должен уметь стирать историю."""
        store = _store(tmp_path, 5)
        try:
            report = store.purge(max_rows=0, max_age_sec=0)

            assert report["remaining"] == 5, "ноль как предел стёр историю"
            assert report["by_rows"] == 0 and report["by_age"] == 0
        finally:
            store.close()

    def test_cut_is_by_arrival_order_not_by_timestamp(self, tmp_path) -> None:
        """Стор общий на процессы, а часы источников идут вразнобой.

        Срез «последние N» по ``ts`` вырезал бы свежие строки процесса с отставшими
        часами. Порядок прихода (``id``) — единственная величина, в которой «последние
        N» значит одно и то же для всех писателей.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            store.append_records([_record(9000.0, "часы-убежали")])
            store.append_records([_record(10.0, "часы-отстали")])

            store.purge(max_rows=1)

            left = [row["message"] for row in store.list_records()]
            assert left == ["часы-отстали"], "срез пошёл по времени, а не по порядку прихода"
        finally:
            store.close()


class TestAgeLimit:
    def test_drops_records_older_than_the_window(self, tmp_path) -> None:
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            store.append_records([_record(100.0, "древняя"), _record(900.0, "свежая")])

            report = store.purge(max_age_sec=300.0, now=1000.0)

            assert report["by_age"] == 1
            assert [row["message"] for row in store.list_records()] == ["свежая"]
        finally:
            store.close()

    def test_both_limits_apply_together(self, tmp_path) -> None:
        """Возраст и число нужны ОБА: всплеск переполняет окно времени, окно
        времени спасает историю от схлопывания до последних секунд всплеска."""
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        try:
            store.append_records([_record(10.0, "древняя")])
            store.append_records([_record(990.0 + i, f"всплеск-{i}") for i in range(5)])

            report = store.purge(max_rows=2, max_age_sec=100.0, now=1000.0)

            assert report["by_age"] == 1, "возраст не сработал"
            assert report["by_rows"] == 3, "предел строк не сработал"
            assert report["remaining"] == 2
        finally:
            store.close()
