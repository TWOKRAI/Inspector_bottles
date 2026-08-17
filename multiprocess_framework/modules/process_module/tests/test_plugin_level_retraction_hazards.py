# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА переутверждения снятия — авторский набор S-1 (нога A).

Дополнение к независимой приёмке ``test_plugin_level_retraction_retry_acceptance.py``
(она судит наблюдаемый эффект на дереве), а не замена. Здесь — внутренности
хранилища, которые в наблюдаемом эффекте не видны, пока не станет поздно.

Что каждый тест сторожит, если сформулировать ДО прогона:

* **Чтение не расходует запас.** Пока «прочитал» и «списал» были одним вызовом
  (``take_retracted``), отказ доставки был неотличим от успеха. Разделение —
  вся суть починки, и его надо держать утверждением: вызвать
  ``pending_retractions`` десять раз подряд и увидеть, что запас цел.
* **Списание конечно и упирается в ноль, а не уходит в минус.** Счётчик,
  ушедший в отрицательное, оставил бы имя в словаре навсегда — то есть
  бесконечный повтор, ровно то, против чего был исходный довод.
* **Повторное снятие даёт ПОЛНЫЙ запас, а не сумму.** Плагин, поднявшийся и
  снова остановленный, — законное событие; складывать запасы значило бы копить
  долг, которого никто не заказывал, и растянуть «нет показания» на десятки
  тактов после десятка перезапусков.
* **Живая публикация убирает имя целиком, а не уменьшает счётчик.** Уменьшение
  оставило бы ``None`` приходить вдогонку уже поднятому плагину.
* **Подтверждение неизвестного имени молчит.** Между чтением и подтверждением
  живая публикация могла отменить снятие — это законная гонка, а не сбой; бросок
  здесь уронил бы такт heartbeat из-за нормального события.
* **Три потока вокруг словаря запасов.** Тот же состав, что у ``_values``:
  публикует воркер плагина, читает и подтверждает heartbeat, снимает поток
  остановки. Словарь, меняющийся во время копирования, поднимает ``RuntimeError``.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    RETRACTION_REASSERT_TICKS,
    PluginLevels,
)


def _store_with_one_level(name: str = "probe", owner: str = "plugin_a") -> PluginLevels:
    store = PluginLevels()
    store.publish(name, 1.0, owner)
    store.retract(owner)
    return store


# --------------------------------------------------------------------------- #
# Чтение против списания
# --------------------------------------------------------------------------- #
class TestReadingDoesNotSpend:
    def test_ten_reads_in_a_row_leave_the_budget_intact(self) -> None:
        """Дренаж был дефектом, а не свойством: чтение обязано быть бесплатным."""
        store = _store_with_one_level()
        for i in range(10):
            assert store.pending_retractions() == {"probe"}, f"чтение №{i + 1} потеряло имя"

    def test_the_returned_set_is_a_copy_not_the_live_store(self) -> None:
        """Отдай живую ссылку — и вызывающий менял бы запасы, ничего не зная.

        Мутация возвращённого множества не имеет права затронуть хранилище.
        """
        store = _store_with_one_level()
        taken = store.pending_retractions()
        taken.add("подброшенное_имя")
        taken.discard("probe")
        assert store.pending_retractions() == {"probe"}, (
            "возврат — живая ссылка на внутренности: правка копии изменила хранилище"
        )

    def test_exactly_the_limit_of_confirmations_forgets_the_name(self) -> None:
        store = _store_with_one_level()
        for i in range(RETRACTION_REASSERT_TICKS - 1):
            store.confirm_retracted(["probe"])
            assert store.pending_retractions() == {"probe"}, (
                f"имя забыто после {i + 1} подтверждений при пределе {RETRACTION_REASSERT_TICKS}"
            )
        store.confirm_retracted(["probe"])
        assert store.pending_retractions() == set(), (
            f"после {RETRACTION_REASSERT_TICKS} подтверждений имя всё ещё утверждается — "
            "«нет показания» превратилось в бесконечную дельту"
        )

    def test_over_confirming_does_not_drive_the_counter_negative(self) -> None:
        """Счётчик, ушедший в минус, оставил бы имя в словаре навсегда.

        Проверяется не «нет исключения», а ЭФФЕКТ: лишние подтверждения не
        воскрешают имя и не роняют вызов.
        """
        store = _store_with_one_level()
        for _ in range(RETRACTION_REASSERT_TICKS + 20):
            store.confirm_retracted(["probe"])
        assert store.pending_retractions() == set()
        assert store._retracted == {}, f"в словаре запасов осталась запись: {store._retracted!r}"


# --------------------------------------------------------------------------- #
# Повторное снятие и живая публикация
# --------------------------------------------------------------------------- #
class TestBudgetLifecycle:
    def test_a_second_retraction_resets_the_budget_to_full_not_to_the_sum(self) -> None:
        """Десять перезапусков не имеют права растянуть «нет показания» на 30 тактов."""
        store = PluginLevels()
        for _ in range(10):
            store.publish("probe", 1.0, "plugin_a")
            store.retract("plugin_a")

        assert store._retracted == {"probe": RETRACTION_REASSERT_TICKS}, (
            f"запасы сложились вместо сброса: {store._retracted!r} — после десяти "
            f"перезапусков дерево получало бы 'None' {store._retracted.get('probe')} тактов"
        )

    def test_a_live_value_removes_the_name_entirely(self) -> None:
        store = _store_with_one_level()
        store.publish("probe", 9.9, "plugin_a")
        assert store.pending_retractions() == set(), (
            "живая публикация лишь уменьшила счётчик — поднятый плагин получит 'None' вдогонку"
        )

    def test_a_live_value_from_ANOTHER_publisher_also_cancels_by_name(self) -> None:
        """Отмена идёт по ИМЕНИ, потому что лист в дереве один.

        Утверждать «показания нет» по имени, в которое кто-то прямо сейчас
        пишет, значило бы гасить живой лист чужим снятием.
        """
        store = _store_with_one_level(name="probe", owner="plugin_a")
        store.publish("probe", 5.0, "plugin_b")
        assert store.pending_retractions() == set(), store._retracted

    def test_confirming_an_unknown_name_is_silent(self) -> None:
        """Гонка «отменили, пока merge летел» — законное событие, не сбой."""
        store = _store_with_one_level()
        store.publish("probe", 9.9, "plugin_a")  # отмена, пока merge летел
        store.confirm_retracted(["probe", "никогда_не_снималось"])  # не должно бросить
        assert store.pending_retractions() == set()

    def test_confirming_one_name_does_not_touch_its_neighbour(self) -> None:
        store = PluginLevels()
        store.publish("a", 1.0, "p")
        store.publish("b", 2.0, "p")
        store.retract("p")
        store.confirm_retracted(["a"])
        assert store._retracted == {
            "a": RETRACTION_REASSERT_TICKS - 1,
            "b": RETRACTION_REASSERT_TICKS,
        }, store._retracted


# --------------------------------------------------------------------------- #
# Три потока вокруг словаря запасов
# --------------------------------------------------------------------------- #
def test_reading_the_budget_while_it_grows_does_not_raise() -> None:
    """Тот же класс, что уже обжёг ``_values``: копия растущего словаря.

    ``dict(self._retracted)`` / ``set(...)`` в момент вставки из другого потока
    поднимает ``RuntimeError: dictionary changed size during iteration``.
    Писателей у запасов столько же, сколько у значений, — значит и лок нужен тот
    же. Тест держит РОСТ (новые ключи), потому что именно рост поднимает ошибку.

    Поток-писатель — daemon с дедлайном join: тест, который вместо падения
    зависает, хуже отсутствующего.
    """
    store = PluginLevels()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer() -> None:
        try:
            i = 0
            while not stop.is_set():
                store.publish(f"level_{i}", float(i), "writer_plugin")
                store.retract("writer_plugin")
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()
    try:
        for _ in range(2000):
            store.pending_retractions()
            store.confirm_retracted(["level_0"])
    finally:
        stop.set()
        thread.join(timeout=5.0)

    assert not thread.is_alive(), "поток-писатель не завершился за 5с"
    assert not errors, f"писатель упал: {errors[0]!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
