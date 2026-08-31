# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА сторожа порядка push/poll — авторский набор S-1 (нога B).

Дополнение к независимой приёмке
``frontend_module/tests/state/test_telemetry_poll_push_ordering_acceptance.py``,
а не замена: приёмка судит НАБЛЮДАЕМЫЙ эффект («устаревший ответ не воскрешает
снятое»), здесь — то, что видно только автору механизма и в наблюдаемом эффекте
не проявляется, пока не станет поздно.

Что каждый тест сторожит, если сформулировать ДО прогона:

* **Граница ``>`` против ``>=``.** Правило отбраковки — ``push_seq[path] >
  requested_at_seq``. Замени его на ``>=``, и приёмка останется зелёной целиком:
  все её сценарии стоят СТРОГО по одну сторону от границы. Различает эти две
  реализации только пара «равенство вливается / +1 отбрасывается», и без неё
  правка ``>`` → ``>=`` прошла бы молча, тихо отбрасывая законные ответы опроса.
* **Словарь номеров не растёт вечно.** ``_push_seq`` — вторая копия множества
  путей, и путь из неё обязан уходить ТАМ ЖЕ, где уходит из снимка. Пути
  приходят и уходят (пересборка топологии, ``deleted=True``); не чистить —
  значит копить строку на каждый когда-либо виденный путь. Утечка растёт
  медленно и не даёт симптома, поэтому её не найдут, а тест обязан.
* **``prime`` — тоже push.** Метод публичный, и повторный залив кэша обязан
  обесценивать ответы, улетевшие до него. Не считать ``prime`` записью значило
  бы оставить дыру ровно там, где снимок меняется целиком.
* **Ответ опроса счётчик не двигает.** Двинь — и первый же влив объявил бы
  устаревшими все запросы, ещё находящиеся в полёте: опрос глушил бы сам себя,
  а выглядело бы это как «опрос иногда не доезжает».
* **Реентерантность.** Влив опроса может случиться ИЗ обработчика push (виджет
  на сигнале ``updated`` дёргает опрос синхронно). Сторож не имеет права
  зависеть от того, доработал ли внешний вызов до конца.
* **Пересоздание read-model.** Счётчик начинается с нуля, а у висящих в полёте
  запросов номер снят с прежней шкалы. Свойство названо и проверено ЯВНО, чтобы
  «сторож защищает всегда» не превратилось в неверную посылку: он вырождается в
  прежнее поведение, а не даёт ложную отбраковку.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

PATH = "processes.cam0.state.probe_level"
OTHER = "processes.cam0.state.fps"


def _model(**kw) -> TelemetryReadModel:
    return TelemetryReadModel(tracked_suffixes=(), **kw)


# --------------------------------------------------------------------------- #
# Граница правила: `==` вливается, `+1` отбрасывается
# --------------------------------------------------------------------------- #
class TestTheBoundaryBetweenStrictAndNonStrict:
    """``>`` и ``>=`` неразличимы без прямого удара по границе.

    Обоснование самой границы — в докстринге ``ingest_poll_snapshot``: счётчик
    увеличивается ПОСЛЕ применения записи, поэтому равенство означает «эта
    push-запись уже была учтена в снимке, против которого снимали номер».
    """

    def test_equality_is_accepted_the_poll_wins(self) -> None:
        m = _model()
        m.ingest(PATH, None)
        seq = m.write_seq  # ровно номер этой push-записи

        applied = m.ingest_poll_snapshot({PATH: 42.0}, requested_at_seq=seq)

        assert applied == [PATH], (
            "на границе push_seq == requested_at_seq ответ опроса обязан ВЛИТЬСЯ "
            f"(правило строгое '>'), но применены пути {applied!r}"
        )
        assert m.get(PATH) == pytest.approx(42.0)

    def test_one_step_past_the_boundary_is_discarded(self) -> None:
        m = _model()
        m.ingest(PATH, None)
        seq = m.write_seq - 1  # запрос «ушёл» ровно на один номер раньше push'а

        applied = m.ingest_poll_snapshot({PATH: 42.0}, requested_at_seq=seq)

        assert applied == [], (
            f"push_seq на 1 больше requested_at_seq — путь обязан быть отброшен, применены {applied!r}"
        )
        assert m.get(PATH) is None

    def test_the_two_assertions_together_pin_strictness(self) -> None:
        """Пара выше — единственное, что отличает ``>`` от ``>=``.

        Здесь это сказано утверждением, а не комментарием: на одном и том же
        экземпляре равный номер вливается, а больший на единицу — нет.
        """
        m = _model()
        m.ingest(PATH, 1.0)
        equal_seq = m.write_seq
        m.ingest(OTHER, 2.0)  # двигаем общий счётчик, номер PATH не трогаем

        assert m.ingest_poll_snapshot({PATH: 10.0}, requested_at_seq=equal_seq) == [PATH]
        assert m.ingest_poll_snapshot({PATH: 20.0}, requested_at_seq=equal_seq - 1) == []


# --------------------------------------------------------------------------- #
# Опасность 1: словарь номеров без предела
# --------------------------------------------------------------------------- #
class TestSeqDictDoesNotOutliveThePaths:
    def test_deleting_a_node_takes_its_sequence_numbers_with_it(self) -> None:
        """Путь ушёл из снимка → номер ушёл вместе с ним, по той же границе.

        Иначе ``_push_seq`` копил бы строку на каждый когда-либо виденный путь:
        рост линейный по числу пересборок топологии, симптома нет, найти нечем.
        """
        m = _model()
        for i in range(50):
            m.ingest(f"processes.cam{i}.state.fps", float(i))
        assert len(m._push_seq) == 50, "предпосылка: номера записаны"

        for i in range(50):
            m.ingest(f"processes.cam{i}", None, deleted=True)

        assert m._push_seq == {}, (
            f"после удаления 50 узлов в словаре номеров осталось {len(m._push_seq)} записей: "
            f"{sorted(m._push_seq)[:5]}… — утечка растёт линейно и молча"
        )

    def test_the_purge_boundary_is_the_dot_not_the_string_prefix(self) -> None:
        """Удаление ``processes.cam`` не забирает номера ``processes.cam2.*``.

        Та же граница, что у снимка и истории. Разойдись они — сосед с общим
        строковым префиксом терял бы защиту сторожа беззвучно.
        """
        m = _model()
        m.ingest("processes.cam.state.fps", 1.0)
        m.ingest("processes.cam2.state.fps", 2.0)

        m.ingest("processes.cam", None, deleted=True)

        assert "processes.cam2.state.fps" in m._push_seq, (
            f"снесены номера соседа по строковому префиксу: {sorted(m._push_seq)}"
        )
        assert "processes.cam.state.fps" not in m._push_seq

    def test_repeated_writes_to_one_path_keep_one_row(self) -> None:
        """Тысяча записей в один путь — одна строка словаря, не тысяча."""
        m = _model()
        for i in range(1000):
            m.ingest(PATH, float(i))
        assert len(m._push_seq) == 1, f"словарь номеров растёт по ЗАПИСЯМ, а не по путям: {len(m._push_seq)}"
        assert m.write_seq == 1000, "счётчик обязан считать каждую запись, а не каждый путь"

    def test_a_deleted_path_that_never_returns_leaves_nothing_behind(self) -> None:
        """Названная цена: удалённый путь теряет и защиту сторожа тоже.

        Не «невозможно» и не «гарантировано» — воспроизведение прямо здесь:
        ответ опроса, снятый ДО удаления, после удаления путь ВОССТАНОВИТ.
        Осознанный обмен (см. докстринг ``_purge_subtree``); тест держит его
        видимым, чтобы смена решения была заметна, а не случайна.
        """
        m = _model()
        m.ingest(PATH, 12.5)
        seq_before_delete = m.write_seq - 1  # запрос ушёл ДО этой записи

        m.ingest("processes.cam0", None, deleted=True)
        applied = m.ingest_poll_snapshot({PATH: 12.5}, requested_at_seq=seq_before_delete)

        assert applied == [PATH], (
            "поведение изменилось: удалённый путь больше не восстанавливается устаревшим "
            "ответом опроса. Это УЛУЧШЕНИЕ, но цена в _purge_subtree описана иначе — "
            "обнови докстринг и этот тест"
        )


# --------------------------------------------------------------------------- #
# Кто двигает счётчик, а кто нет
# --------------------------------------------------------------------------- #
class TestWhoMovesTheCounter:
    def test_prime_counts_as_a_push_write(self) -> None:
        m = _model()
        before = m.write_seq
        m.prime({PATH: 1.0, OTHER: 2.0})
        assert m.write_seq == before + 2, f"prime не сдвинул счётчик на число путей: было {before}, стало {m.write_seq}"

    def test_a_reprime_invalidates_a_poll_request_sent_before_it(self) -> None:
        """Повторный залив кэша обесценивает улетевший ранее запрос."""
        m = _model()
        seq = m.write_seq
        m.prime({PATH: None})
        assert m.ingest_poll_snapshot({PATH: 99.0}, requested_at_seq=seq) == [], (
            "ответ опроса, отправленный ДО повторного prime, влился поверх свежего снимка"
        )

    def test_a_delete_counts_as_a_push_write_too(self) -> None:
        m = _model()
        m.ingest(PATH, 1.0)
        before = m.write_seq
        m.ingest("processes.cam0", None, deleted=True)
        assert m.write_seq == before + 1, (
            f"удаление узла — принятая запись push-дороги, а счётчик не двинулся: {before} → {m.write_seq}"
        )

    def test_a_poll_ingest_never_moves_the_counter(self) -> None:
        """Двинь счётчик ответом опроса — и опрос заглушит сам себя.

        Все запросы, находящиеся в полёте, мгновенно стали бы «отправленными
        раньше последней записи», и следующий влив отбросил бы их пути целиком.
        Симптом («опрос иногда не доезжает») увёл бы искать в транспорт.
        """
        m = _model()
        before = m.write_seq
        m.ingest_poll_snapshot({PATH: 1.0, OTHER: 2.0}, requested_at_seq=before)
        assert m.write_seq == before, f"ответ опроса сдвинул счётчик push-записей: {before} → {m.write_seq}"

    def test_the_counter_never_goes_backwards(self) -> None:
        m = _model()
        seen = [m.write_seq]
        for i in range(20):
            m.ingest(f"p{i % 3}", float(i))
            m.ingest_poll_snapshot({f"p{i % 3}": float(i)}, requested_at_seq=m.write_seq)
            seen.append(m.write_seq)
        assert seen == sorted(seen), f"счётчик не монотонен: {seen}"
        assert len(set(seen)) > 1, "предпосылка: счётчик вообще двигался"


# --------------------------------------------------------------------------- #
# Опасность 4: влив опроса ВНУТРИ обработки push
# --------------------------------------------------------------------------- #
class TestReentrancy:
    def test_a_poll_ingest_nested_inside_a_push_sees_the_completed_push(self) -> None:
        """Реентерантный влив судится по УЖЕ применённой push-записи.

        Живая дорога: виджет на сигнале обновления дёргает опрос синхронно.
        Порядок «снимок обновлён → номер сдвинут» обязан быть неделим с точки
        зрения любого вложенного читателя: увидь тот половину, и запись, уже
        лежащая в снимке, оказалась бы «ещё не случившейся» — сторож пропустил
        бы ровно тот ответ, ради которого заведён.
        """
        m = _model()
        seq_at_request = m.write_seq

        # Внешний вызов: push, который «спровоцировал» вложенный влив опроса.
        m.ingest(PATH, None)
        # Вложенный влив — в момент, когда внешняя запись уже применена.
        applied = m.ingest_poll_snapshot({PATH: 7.0}, requested_at_seq=seq_at_request)

        assert applied == [], "вложенный влив не увидел только что применённую push-запись"
        assert m.get(PATH) is None

    def test_nested_polls_do_not_corrupt_the_counter(self) -> None:
        m = _model()
        m.ingest(PATH, 1.0)
        seq = m.write_seq
        for _ in range(5):
            m.ingest_poll_snapshot({OTHER: 1.0}, requested_at_seq=seq)
        assert m.write_seq == seq, "серия вложенных вливов сдвинула счётчик"


# --------------------------------------------------------------------------- #
# Опасность 3: пересоздание read-model под висящими запросами
# --------------------------------------------------------------------------- #
class TestCounterResetOnModelRecreation:
    def test_a_seq_from_a_previous_model_degrades_to_the_old_behaviour(self) -> None:
        """Свежий экземпляр не защищает — но и не врёт.

        Номер, снятый с ПРЕЖНЕГО экземпляра, для нового — число чужой шкалы.
        У свежего ``_push_seq`` пуст, поэтому ответ применяется целиком, как и
        до починки. Утверждение написано ЯВНО, потому что альтернатива —
        «сторож защищает всегда» — была бы неверной посылкой, на которую потом
        сослались бы в разборе живого дефекта.
        """
        old = _model()
        for _ in range(500):
            old.ingest(PATH, 1.0)
        seq_from_old = old.write_seq
        assert seq_from_old == 500, "предпосылка: у прежнего экземпляра счётчик ушёл далеко"

        fresh = _model()
        applied = fresh.ingest_poll_snapshot({PATH: 12.5}, requested_at_seq=seq_from_old)

        assert applied == [PATH], (
            "поведение изменилось: свежий read-model теперь отбраковывает по номеру из чужой "
            "шкалы. Возможно, это правильнее — но тогда правило надо описать, а не получить"
        )

    def test_a_stale_seq_larger_than_the_counter_never_drops_anything(self) -> None:
        """Номер «из будущего» — это «всё свежее», а не «всё устарело».

        Обратная ошибка была бы куда хуже: сторож молча съедал бы КАЖДЫЙ ответ,
        и карточка перестала бы обновляться вовсе.
        """
        m = _model()
        m.ingest(PATH, 1.0)
        applied = m.ingest_poll_snapshot({PATH: 99.0}, requested_at_seq=10**9)
        assert applied == [PATH], "номер из будущего вызвал отбраковку — сторож глушит опрос целиком"


# --------------------------------------------------------------------------- #
# Второй инвариант не имеет права сломать первый
# --------------------------------------------------------------------------- #
def test_the_poll_entry_still_writes_no_history() -> None:
    """Инвариант 1 (ADR-139) переживает появление инварианта 2."""
    m = TelemetryReadModel(tracked_suffixes=(".state.fps",), window_sec=10.0, sample_hz=1.0)
    m.ingest_poll_snapshot({"processes.cam.state.fps": 5.0}, requested_at_seq=0)
    assert m.history("processes.cam.state.fps") == [], "влив опроса записал точку в кольцо истории"


def test_a_partially_stale_response_applies_the_rest() -> None:
    """Судится КАЖДЫЙ путь: один отброшен, два влиты — из одного ответа."""
    m = _model()
    seq = m.write_seq
    m.ingest(PATH, None)  # push только по одному пути

    applied = m.ingest_poll_snapshot({PATH: 1.0, OTHER: 2.0, "processes.cam0.state.uptime": 3.0}, requested_at_seq=seq)

    assert set(applied) == {OTHER, "processes.cam0.state.uptime"}, applied
    assert m.get(PATH) is None
    assert m.get(OTHER) == pytest.approx(2.0)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
