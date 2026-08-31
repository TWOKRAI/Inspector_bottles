# -*- coding: utf-8 -*-
"""Ф5 (5.1) — опасности МЕХАНИЗМА дампа, видимые автору.

Здесь не приёмка (её пишет независимый тестер от критериев, не видя кода), а
то, что можно знать только изнутри устройства: в какой момент снимается кольцо,
что делает второй поток, чем кончается несериализуемый объект в ``extra``, где
проходит граница ретеншена и что происходит с голосом вытеснения, который сам
уезжает в то же кольцо.

Проводка настоящая на всех тестах, где судится дорога (реальный
``LoggerManager`` с memory-каналом, реальный ``ProcessModule``, реальный
``PluginContext``, реальные файлы). Дубли — только там, где надо СЛОМАТЬ то,
что настоящий объект ломать не умеет (отказ файловой системы).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import (
    MANIFEST_KIND,
    UNREADABLE_KIND,
    FlightRecorder,
    apply_flight_recorder,
    flight_plane_report,
    reason_slug,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, SubPluginContext

RING = "ring"


def _logger_config(tmp_path: Path, capacity: int = 500) -> Dict[str, Any]:
    """Логгер с ФАЙЛОМ и КОЛЬЦОМ на обоих скоупах.

    Файл рядом с кольцом не для красоты: он — контроль. Без него «в дампе пусто»
    читалось бы одинаково и при мёртвой проводке, и при рабочей с пустым кольцом.
    """
    return {
        "app_name": "flight",
        "log_directory": str(tmp_path),
        "modules": {},
        "channels": {
            "a": {"type": "file", "enabled": True, "file_path": "a.log"},
            RING: {"type": "memory", "enabled": True, "capacity": capacity},
            "plain_file": {"type": "file", "enabled": True, "file_path": "plain.log"},
        },
        "scopes": {
            "SYSTEM": {"channels": ["a", RING]},
            "BUSINESS": {"channels": ["a", RING]},
            "DEBUG": {"channels": ["a", RING]},
        },
    }


def _make(tmp_path: Path, flight: Dict[str, Any], capacity: int = 500):
    """Настоящая проводка процесса: логгер → кольцо → рекордер → контекст."""
    proc = ProcessModule("inspector", config={"observability_app": {"flight": flight}})
    logger = LoggerManager(manager_name="FlightLog", config=_logger_config(tmp_path, capacity), process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    return proc, ctx, logger


@pytest.fixture
def wired(tmp_path: Path):
    proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 0})
    try:
        yield proc, ctx, tmp_path
    finally:
        logger.shutdown()


def _flight_dir(tmp_path: Path) -> Path:
    return tmp_path / "inspector" / "flight"


def _dumps(tmp_path: Path) -> List[Path]:
    directory = _flight_dir(tmp_path)
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


def _lines(path: Path) -> List[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestTheRingIsTakenAtTheMomentOfTheCall:
    """Порядок «дамп ПОСЛЕ широкой записи» — свойство механизма, не соглашение."""

    def test_a_record_written_before_is_in_and_after_is_not(self, wired) -> None:
        """Кольцо снимается В МОМЕНТ вызова, и это единственная причина Р5.1-11.

        Пункт приёмки «в дампе wide event бракованной единицы» держится не тем,
        что плагин так написан, а тем, что дамп не видит будущего. Позови его
        плагин строкой выше — пункт был бы зелёным на пустом месте, и никакой
        тест эмитента этого бы не поймал.
        """
        _, ctx, tmp_path = wired
        ctx.log_info("ДО ДАМПА")

        assert ctx.flight_dump("reject") is True

        ctx.log_info("ПОСЛЕ ДАМПА")
        body = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in _lines(_dumps(tmp_path)[0]))
        assert "ДО ДАМПА" in body
        assert "ПОСЛЕ ДАМПА" not in body, "дамп не имеет права видеть записи, сделанные после него"

    def test_the_wide_event_of_the_unit_lands_in_the_dump(self, wired) -> None:
        """Широкая запись — обычная запись плоскости логов, значит она в кольце.

        Проверяется по СОДЕРЖИМОМУ дампа, а не по факту вызова: `write_event`
        едет носителем `log_info`, и связь «носитель → кольцо» держится
        маршрутом скоупа, который рецепт обязан задать (Р5.1-7).
        """
        proc, ctx, tmp_path = wired
        from multiprocess_framework.modules.process_module.managers.observability_wiring import WideEventSelector

        proc.event_selector = WideEventSelector(first_n=10, every_mth=1)
        ctx.write_event("inspection", "reject: дефектов 3", unit={"trace_id": "deadbeef"}, decisive=True)

        assert ctx.flight_dump("reject", trace_id="deadbeef") is True

        records = _lines(_dumps(tmp_path)[0])
        assert records[0]["kind"] == MANIFEST_KIND
        assert records[0]["trace_id"] == "deadbeef", "шапка обязана нести след единицы"
        assert any("trace=deadbeef" in str(rec.get("message", "")) for rec in records[1:])


class TestTheManifestExplainsTheCount:
    """Число записей в дампе нечитаемо без снимка кольца."""

    def test_the_header_carries_the_ring_snapshot(self, tmp_path: Path) -> None:
        """«12 записей, потому что столько было» ≠ «потому что 488 вытеснено».

        Кольцо ёмкостью 4 под 12 записями обязано показать в шапке ненулевой
        ``evicted``: без него счёт строк дампа выглядит как полнота.
        """
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 0}, capacity=4)
        try:
            for i in range(12):
                ctx.log_info(f"строка {i}")
            assert ctx.flight_dump("overflow") is True
            header = _lines(_dumps(tmp_path)[0])[0]
        finally:
            logger.shutdown()

        assert header["ring"]["capacity"] == 4
        assert header["ring"]["size"] == 4
        assert header["ring"]["evicted"] > 0, "вытеснение обязано быть видно в шапке"
        assert header["records"] == 4

    def test_limit_cuts_the_tail_and_the_header_says_so(self, wired) -> None:
        """``limit`` берёт ПОСЛЕДНИЕ N — иначе дамп отвечал бы про начало смены."""
        proc, ctx, tmp_path = wired
        for i in range(20):
            ctx.log_info(f"строка {i}")
        apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": RING, "keep": 0, "limit": 5})

        assert ctx.flight_dump("cut") is True

        records = _lines(_dumps(tmp_path)[0])
        assert records[0]["records"] == 5
        assert records[0]["limit"] == 5
        assert len(records) == 6, "шапка + пять записей"
        assert "строка 19" in str(records[-1]["message"]), "берётся хвост, а не голова"


class TestTheTwoNamedRefusals:
    """Р5.1-6: два диагноза — два текста, два счётчика. И ни один не тишина."""

    def test_disabled_names_the_knob_and_writes_nothing(self, tmp_path: Path) -> None:
        proc, ctx, logger = _make(tmp_path, {"enabled": False, "sink": RING})
        try:
            assert ctx.flight_dump("reject") is False
            report = flight_plane_report(proc)["flight"]
        finally:
            logger.shutdown()

        assert report["refused_disabled"] == 1
        assert report["refused_no_ring"] == 0, "диагнозы не имеют права слипнуться"
        assert _dumps(tmp_path) == []
        said = (tmp_path / "inspector" / "a.log").read_text(encoding="utf-8", errors="replace")
        assert "observability.flight.enabled" in said, "WARNING без адреса не говорит, что править"

    def test_a_file_sink_is_a_different_diagnosis(self, tmp_path: Path) -> None:
        """Ловушка Р5.1-7 живьём: приёмник ЕСТЬ, но записей не хранит.

        Это ровно тот дефект, который в диффе рецепта не виден: забыл
        ``type: memory`` — поднялся файловый канал под тем же именем. Механизм
        обязан назвать это ОТДЕЛЬНО от «выключено», потому что лечится оно
        другим ключом.
        """
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": "plain_file"})
        try:
            assert ctx.flight_dump("reject") is False
            report = flight_plane_report(proc)["flight"]
        finally:
            logger.shutdown()

        assert (report["refused_no_ring"], report["refused_disabled"]) == (1, 0)
        assert _dumps(tmp_path) == []
        said = (tmp_path / "inspector" / "a.log").read_text(encoding="utf-8", errors="replace")
        assert "plain_file" in said and "observability.flight.sink" in said

    def test_an_unknown_sink_is_the_same_class(self, tmp_path: Path) -> None:
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": "нет-такого"})
        try:
            assert ctx.flight_dump("reject") is False
            assert flight_plane_report(proc)["flight"]["refused_no_ring"] == 1
        finally:
            logger.shutdown()

    def test_the_voice_is_said_once_and_the_counter_always(self, tmp_path: Path) -> None:
        """Голос на каждый кадр брака превратил бы отказ в шторм. Число — нет."""
        proc, ctx, logger = _make(tmp_path, {"enabled": False, "sink": RING})
        try:
            for _ in range(5):
                ctx.flight_dump("reject")
            said = (tmp_path / "inspector" / "a.log").read_text(encoding="utf-8", errors="replace")
            assert flight_plane_report(proc)["flight"]["refused_disabled"] == 5
        finally:
            logger.shutdown()
        assert said.count("flight recorder выключен") == 1

    def test_a_missing_recorder_answers_the_same_refusal(self, tmp_path: Path) -> None:
        """Р5.1-5: у «выключено» ОДНО состояние с ОДНИМ адресом.

        Процесс без сшивки обязан отвечать ровно тем же текстом и тем же
        счётчиком, что настроенный рекордер с ``enabled=False``. Два разных
        ответа означали бы, что оператор чинит наличие механизма вместо ручки.
        """
        proc = ProcessModule("inspector")
        ctx = PluginContext(services=proc, plugin_name="robot_control")

        assert proc.flight_recorder is None, "сшивки не было — это и есть проверяемое состояние"
        assert ctx.flight_dump("reject") is False

        report = flight_plane_report(proc)["flight"]
        assert report["declared"] is False, "«механизма нет» обязано отличаться от «есть и выключен»"
        assert report["refused_disabled"] == 1, "отказ считается и БЕЗ рекордера"


class TestUnserializablePayload:
    """``extra`` держит ссылки на объекты вызывающего — сказано в докстринге редактора."""

    def test_one_bad_record_does_not_cost_the_dump(self, wired) -> None:
        """Циклическая ссылка в ``extra`` стоит СВОЕЙ строки, а не 499 соседей.

        Молчаливый пропуск запрещён отдельно: счёт строк — то, чем судят
        полноту дампа, и дырка без заглушки сдвинула бы его незаметно.
        """
        _, ctx, tmp_path = wired
        loop: Dict[str, Any] = {}
        loop["self"] = loop
        ctx.log_info("ЦЕЛАЯ ДО")
        ctx.log_info("БИТАЯ", cycle=loop)
        ctx.log_info("ЦЕЛАЯ ПОСЛЕ")

        assert ctx.flight_dump("bad") is True

        records = _lines(_dumps(tmp_path)[0])
        broken = [rec for rec in records if rec.get("kind") == UNREADABLE_KIND]
        assert len(broken) == 1, "битая запись обязана оставить след на своём месте"
        assert broken[0]["index"] >= 0
        body = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in records)
        assert "ЦЕЛАЯ ДО" in body and "ЦЕЛАЯ ПОСЛЕ" in body, "соседи целы"

    def test_a_bad_header_field_does_not_cost_the_dump_either(self, wired) -> None:
        """Шапка обязательна: без неё счёт записей нечитаем. Значит — второй заход."""
        _, ctx, tmp_path = wired
        loop: Dict[str, Any] = {}
        loop["self"] = loop
        ctx.log_info("ЗАПИСЬ")

        assert ctx.flight_dump("bad-header", trace_id="t1", broken=loop) is True

        header = _lines(_dumps(tmp_path)[0])[0]
        assert header["kind"] == MANIFEST_KIND
        assert "fields_unreadable" in header, "причина обязана быть в самой шапке"
        assert header["reason"] == "bad-header", "собственные ключи шапки уцелели"
        assert "trace_id" not in header, "прикладные поля сняты ЦЕЛИКОМ — второй разбор не гадает"

    def test_objects_without_json_form_survive_via_default_str(self, wired) -> None:
        """``default=str`` — не украшение: в ``extra`` кладут что угодно."""
        _, ctx, tmp_path = wired
        ctx.log_info("ОБЪЕКТ", thing=object(), path=Path("x"))

        assert ctx.flight_dump("obj") is True
        records = _lines(_dumps(tmp_path)[0])
        assert not [rec for rec in records if rec.get("kind") == UNREADABLE_KIND]


class TestRetention:
    """Граница K / K+1 — там, где ретеншен либо считает, либо ошибается на единицу."""

    def test_k_dumps_fit_and_the_k_plus_first_evicts_the_oldest(self, tmp_path: Path) -> None:
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 3})
        try:
            for i in range(3):
                assert ctx.flight_dump(f"d{i}") is True
            at_k = [p.name for p in _dumps(tmp_path)]
            assert len(at_k) == 3, "на границе K не вытесняется ничего"

            assert ctx.flight_dump("d3") is True
            at_k1 = [p.name for p in _dumps(tmp_path)]
            report = flight_plane_report(proc)["flight"]
            said = (tmp_path / "inspector" / "a.log").read_text(encoding="utf-8", errors="replace")
        finally:
            logger.shutdown()

        assert len(at_k1) == 3, "держим ровно K"
        assert at_k[0] not in at_k1, "ушёл СТАРЕЙШИЙ"
        assert at_k[1] in at_k1 and at_k[2] in at_k1
        assert report["evicted_files"] == 1
        assert at_k[0] in said, "молчаливое удаление улики хуже строки в журнале (Р5.1-10)"

    def test_keep_zero_means_no_limit(self, tmp_path: Path) -> None:
        """``0 = без предела`` — уже написанная в проекте форма, третьей не заводим."""
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 0})
        try:
            for i in range(6):
                assert ctx.flight_dump(f"d{i}") is True
            assert len(_dumps(tmp_path)) == 6
            assert flight_plane_report(proc)["flight"]["evicted_files"] == 0
        finally:
            logger.shutdown()

    def test_lowering_keep_on_a_live_recorder_trims_on_the_next_dump(self, tmp_path: Path) -> None:
        """Ручку крутят посреди смены. Новый предел обязан подействовать сразу."""
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 0})
        try:
            for i in range(5):
                ctx.flight_dump(f"d{i}")
            apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": RING, "keep": 2})
            ctx.flight_dump("after")
            assert len(_dumps(tmp_path)) == 2
        finally:
            logger.shutdown()

    def test_the_eviction_voice_lands_in_the_NEXT_dump_not_this_one(self, tmp_path: Path) -> None:
        """Реентерантность названа, а не случайна.

        Голос вытеснения уходит в тот же логгер, то есть в то же кольцо. Кольцо
        снято ДО вытеснения, поэтому в текущем дампе строки о нём нет и быть не
        может; в следующем — есть. Читатель дампа обязан это знать: увидев
        «вытеснен старый дамп», он смотрит на событие ПРОШЛОГО раза.
        """
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 1})
        try:
            ctx.flight_dump("first")
            ctx.flight_dump("second")  # вытеснит first и скажет об этом
            evicting = _dumps(tmp_path)[-1]
            body_now = evicting.read_text(encoding="utf-8")
            ctx.flight_dump("third")
            body_next = _dumps(tmp_path)[-1].read_text(encoding="utf-8")
        finally:
            logger.shutdown()

        assert "вытеснен старый дамп" not in body_now, "дамп не видит собственного следствия"
        assert "вытеснен старый дамп" in body_next, "…но следующий видит, и это не потеря"


class TestTheFilesystemFails:
    """Третий класс отказа: кольцо прочитано, файл не написан. Лечится машиной."""

    def test_a_write_failure_is_counted_named_and_does_not_raise(self, wired, monkeypatch) -> None:
        """Р5.1-14: отказ дампа линию не роняет и решения не меняет.

        Дубль здесь обязателен: настоящая ФС в тесте отказывать не умеет, а
        молчаливый ``return False`` на отказе диска — ровно класс «проглоченный
        сбой», ради которого весь этот план и затевался.
        """
        proc, ctx, tmp_path = wired

        def boom(self, *args, **kwargs):
            raise OSError("диск переполнен")

        monkeypatch.setattr(Path, "write_text", boom)

        assert ctx.flight_dump("reject") is False

        report = flight_plane_report(proc)["flight"]
        assert report["refused_failed"] == 1
        assert (report["refused_disabled"], report["refused_no_ring"]) == (0, 0), "три диагноза не слипаются"
        assert report["dumps"] == 0, "неудавшийся дамп не имеет права считаться сделанным"


def _run_threads(target, count: int, *, deadline: float = 10.0) -> List[BaseException]:
    """Запустить ``count`` демон-потоков и дождаться каждого с дедлайном.

    Демоны и ``join(timeout)`` обязательны: тест, который ВИСНЕТ вместо падения,
    прячет регрессию за таймаутом раннера и хуже отсутствующего.
    """
    errors: List[BaseException] = []
    start = threading.Barrier(count)

    def worker(n: int) -> None:
        try:
            start.wait(timeout=5)
            target(n)
        except BaseException as exc:  # noqa: BLE001 — падение потока обязано долететь
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=deadline)
        assert not thread.is_alive(), "дамп завис — это хуже, чем упал"
    return errors


class TestConcurrency:
    """Что лок держит НА САМОМ ДЕЛЕ — и чего он не держит.

    **Прежний сторож этого класса был вакуумен**, и это установлено замером, а не
    подозрением (ревью 5.1). Он утверждал «без лока потоки вытеснят больше, чем
    просили», и снятие лока ЦЕЛИКОМ (``RLock`` → ``nullcontext``) не красило ни
    одного теста из 81. Свойство не только не сторожилось — его не существует:
    100 раундов (8 потоков/``keep=4`` и 32/``keep=2``) не дали НИ ОДНОГО раунда
    ниже ``keep``. Перевытеснение невозможно по построению: каждый поток удаляет
    ``files[:len-keep]`` — префикс глобально отсортированного списка, а
    объединение префиксов не длиннее ``N-keep``.

    Лок при этом несущий, просто держит другое: бухгалтерию (``+=`` — неатомарный
    read-modify-write) и TOCTOU имени между ``_resolve_path`` и ``_write``.
    Частота попадания в это окно машинно-зависима: ревьюер намерил 7 нарушений
    инварианта из 40 раундов, автор на том же арме — **0 из 20**. Поэтому
    доказывает лок только барьерный тест ниже, а инвариант бухгалтерии проверяется
    как свойство.
    """

    def test_the_dump_is_mutually_exclusive_end_to_end(self, tmp_path: Path, monkeypatch) -> None:
        """Барьер ВНУТРИ критической секции обязан СЛОМАТЬСЯ по таймауту.

        Это единственная форма, которая доказывает взаимное исключение
        детерминированно. Шторм потоков его не доказывает: GIL не даёт вклиниться
        достаточно часто, поэтому «N потоков — и всё сошлось» остаётся зелёным и
        при полностью снятом локе (ровно то, что случилось с прежним сторожем).

        Механика: шпион на ``_write`` (он зовётся ИЗ-ПОД лока) ждёт на барьере
        двоих. Держим лок — второй поток стоит на входе, барьер не собирается и
        рвётся по таймауту, что здесь и есть УСПЕХ. Снимем лок — оба окажутся в
        секции одновременно, барьер соберётся, и тест покраснеет.

        Дамп при этом доводится до конца в обоих случаях: ``BrokenBarrierError``
        ловится в шпионе, а не роняет запись, — иначе тест судил бы обработку
        исключения, а не взаимное исключение.
        """
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": 0})
        inside = threading.Barrier(2)
        broke: List[bool] = []
        real_write = FlightRecorder._write

        def spy(self, *args, **kwargs):
            try:
                inside.wait(timeout=0.4)
            except threading.BrokenBarrierError:
                broke.append(True)
            return real_write(self, *args, **kwargs)

        monkeypatch.setattr(FlightRecorder, "_write", spy)
        try:
            errors = _run_threads(lambda n: ctx.flight_dump(f"t{n}"), 2)
            report = flight_plane_report(proc)["flight"]
        finally:
            logger.shutdown()

        assert not errors, f"дамп бросил наружу: {errors}"
        assert report["dumps"] == 2, "предпосылка: оба дампа дошли до конца"
        assert broke, "барьер внутри критической секции СОБРАЛСЯ — два потока были в ней одновременно"

    def test_parallel_dumps_keep_the_accounting_straight(self, tmp_path: Path) -> None:
        """Под конкуренцией сходится бухгалтерия: ``dumps == на диске + вытеснено``.

        **Это СВОЙСТВО, а не доказательство лока, и разница названа честно.** На
        машине автора снятие лока не покрасило этот тест **ни разу из 20** (арм
        ревьюера: 32 потока, ``keep=2`` — тот же, на котором он намерил 7
        нарушений из 40). Окно ``+=`` реально, его прячет GIL, и рассчитывать на
        воспроизводимую поломку здесь нельзя. Взаимное исключение доказывает
        сосед выше — детерминированно.

        Тест всё равно стоит: инвариант, по которому судят полноту улик, обязан
        быть записан и проверяться. Просто он ловит не «лок сняли», а «счётчик
        разошёлся с диском» — по любой причине, включая будущие правки ретеншена.

        ``len(files) == keep`` оставлен КОНТРОЛЕМ, а не доказательством лока:
        замер показал, что это свойство держится и без лока (100 раундов, ни
        одного раунда ниже ``keep``).
        """
        keep, count = 2, 32
        proc, ctx, logger = _make(tmp_path, {"enabled": True, "sink": RING, "keep": keep})
        try:
            errors = _run_threads(lambda n: ctx.flight_dump(f"t{n}"), count)
            report = flight_plane_report(proc)["flight"]
            files = _dumps(tmp_path)
        finally:
            logger.shutdown()

        assert not errors, f"дамп бросил наружу: {errors}"
        assert report["dumps"] == count, f"посчитано {report['dumps']} дампов из {count} — счётчик потерял инкремент"
        assert report["dumps"] == len(files) + report["evicted_files"], (
            f"бухгалтерия разошлась: dumps={report['dumps']}, на диске={len(files)}, "
            f"вытеснено={report['evicted_files']}"
        )
        assert len({p.name for p in files}) == len(files), "имена уникальны — перезаписи улик нет"
        assert len(files) == keep, f"контроль (не доказательство лока): держим keep={keep}, а не {len(files)}"


class TestKnobsSurviveTheRebuild:
    """Пересборка меняет ПАРАМЕТРЫ, а не состояние."""

    def test_apply_changes_knobs_without_resetting_counters(self, wired) -> None:
        proc, ctx, _ = wired
        ctx.flight_dump("first")
        before = flight_plane_report(proc)["flight"]["dumps"]

        applied = apply_flight_recorder(proc.flight_recorder, {"enabled": True, "sink": RING, "keep": 9, "limit": 3})

        assert applied == {"enabled": True, "sink": RING, "keep": 9, "limit": 3}
        after = flight_plane_report(proc)["flight"]
        assert after["dumps"] == before, "счёт дампов обязан пережить правку конфига"
        assert (after["keep"], after["limit"]) == (9, 3)

    def test_garbage_in_the_section_keeps_the_previous_policy(self, wired) -> None:
        """Опечатка в ручке дампа не имеет права стоить применения всего остального."""
        proc, _, _ = wired
        before = proc.flight_recorder.knobs

        assert apply_flight_recorder(proc.flight_recorder, {"keep": "много"}) is not None
        assert proc.flight_recorder.knobs == before, "мусор → прежняя политика, а не тихий дефолт"

    def test_apply_on_a_process_without_a_recorder_is_not_a_failure(self) -> None:
        assert apply_flight_recorder(None, {"enabled": True}) is None


class TestTheFacadeSignature:
    """Урок 1.1 (четыре заглушки) и урок 4.1-И8 (позиционный уезжает в **fields)."""

    def test_reason_as_a_keyword_does_not_raise_and_becomes_a_field(self, wired) -> None:
        """``reason`` позиционный — значит прикладной ключ с тем же именем едет в шапку.

        Не падает (это и есть смысл ``/``) и НЕ подменяет причину дампа: причина
        осталась пустой, а прикладное значение легло полем. Проверяется оба
        утверждения — «не упало» одно ничего не доказывает.
        """
        _, ctx, tmp_path = wired

        assert ctx.flight_dump(**{"reason": "ЧУЖОЕ"}) is True

        header = _lines(_dumps(tmp_path)[0])[0]
        assert header["reason"] == "", "конверт кладётся ПОСЛЕ **fields — причина осталась своей"
        assert _dumps(tmp_path)[0].name.endswith("_dump.jsonl"), "пустая причина даёт читаемое имя"

    def test_the_sub_plugin_stub_takes_the_same_call(self) -> None:
        """Заглушка вложенного контекста обязана принять ТОТ ЖЕ вызов.

        Урок 1.1 стоил ровно этого: страховка от падения сама была падением на
        именованном вызове по эталонной сигнатуре.
        """
        sub = SubPluginContext()
        assert sub.flight_dump("reject", trace_id="t") is False
        assert sub.flight_dump(**{"reason": "ЧУЖОЕ"}) is False

    def test_from_parent_forwards_the_road(self) -> None:
        """Единственное перечисление дорог — иначе дефект воскресает на соседней развилке."""
        parent = SubPluginContext(flight_dump=lambda *a, **k: True)
        assert SubPluginContext.from_parent(parent).flight_dump("x") is True


class TestSecretsDoNotGainABypass:
    """Р5.1-12: редактор стоит ДО кольца, и судим мы ФАЙЛ ДАМПА, а не кольцо."""

    def test_a_secret_is_masked_in_the_dump_file(self, wired) -> None:
        """Дамп не открывает обходной дороги: он читает то, что уже отредактировано.

        Судится именно файл на диске — проверка кольца доказывала бы свойство
        логгера, а вопрос задачи в том, не появилось ли ВТОРОЕ место, где
        секрет всплывает.
        """
        _, ctx, tmp_path = wired
        ctx.log_info("подключение", password="hunter2", frame_id=17)

        assert ctx.flight_dump("secret") is True

        body = _dumps(tmp_path)[0].read_text(encoding="utf-8")
        assert "hunter2" not in body, "секрет не имеет права появиться в дампе"
        assert "***" in body
        assert '"frame_id": 17' in body, "контроль: соседнее поле не замаскировано"


class TestTheSlug:
    """Имя файла собирается из прикладной строки — и уезжает с машины скриптами."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("reject", "reject"),
            ("", "dump"),
            # Разделителя пути в результате нет по построению; точки по краям
            # снимаются, чтобы не родить имя ``..`` — гигиена, не защита.
            ("../../etc/passwd", "etc_passwd"),
            ("..", "dump"),
            # Кириллица вырождается — названо в докстринге, полная причина в шапке.
            ("брак линии 7", "7"),
            ("a" * 80, "a" * 40),
        ],
    )
    def test_reason_becomes_a_safe_component(self, raw: str, expected: str) -> None:
        assert reason_slug(raw) == expected

    def test_no_path_separator_can_survive(self, wired) -> None:
        """Свойство важнее таблицы выше: имя дампа обязано остаться ОДНИМ компонентом."""
        _, ctx, tmp_path = wired
        assert ctx.flight_dump("a/b\\c") is True
        assert _dumps(tmp_path)[0].parent == _flight_dir(tmp_path)


class TestTheRecorderInIsolation:
    """Мелочи политики, которым живая проводка не нужна."""

    def test_negative_knobs_are_clamped_not_rejected(self) -> None:
        """Границы держит схема; второй предохранитель сделал бы неизвестным, кто держит."""
        assert FlightRecorder(True, RING, -5, -1).knobs == (True, RING, 0, 0)

    def test_the_sink_name_is_stripped(self) -> None:
        assert FlightRecorder(True, "  ring  ").knobs[1] == RING
