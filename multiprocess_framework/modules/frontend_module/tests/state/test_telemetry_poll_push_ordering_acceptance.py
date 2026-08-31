"""Независимая приёмка механизма B — ответ опроса не имеет права воскресить
снятое значение.

Пишутся ДО реализации, от текста постановки, полученного НАПРЯМУЮ в задании
(не из плана и не из авторских тестов). Этой роли запрещено читать:
`plans/QUEUE.md`, `docs/sessions/2026-08-17.md`, любой `*_hazards.py` в тестах
`process_module`/`frontend_module`, и (с обновления координатора 2026-08-17,
пока реализация пишется параллельно) `frontend_module/state/telemetry_view_model.py`,
`frontend_module/state/telemetry_poller.py`,
`telemetry_readmodel_module/telemetry_read_model.py`. Импорт `TelemetryViewModel`
ниже использует УЖЕ известный из предыдущего чтения (до обновления координатора)
публичный контракт конструктора/`on_state_delta`/`get`/`snapshot`/`history` —
новых обращений к этим файлам нет.

Контракт (дословно из постановки):
    B1. Запрос опроса отправлен; ЗАТЕМ push со значением None по тому же пути;
        ЗАТЕМ ответ опроса с числом по этому же пути → в снимке остаётся None
        (число опроса отброшено как устаревшее).
    B2. Обратный порядок: push, ПОТОМ отправлен запрос, ПОТОМ ответ → число
        опроса влито.
    B3. Отброшенное учтено ЧИСЛОМ — счётчик расхождения push/poll доступен
        наблюдателю и растёт ровно на число отброшенных путей.
    B4. Судится КАЖДЫЙ путь отдельно: в одном ответе опроса один путь отброшен
        как устаревший, другой (без push'а) — влит. Оба факта в одном тесте.
    B5. История не пишется ответом опроса (контроль, существующее поведение).

ОБНОВЛЕНО (2026-08-17): первая редакция этого файла угадывала форму упорядочивания
как инъекцию часов (``clock=``) — координатор назвал это неверной моделью
(своей виной, не тестера) и дал форму контракта НАПРЯМУЮ, без места для догадки:

  * ``TelemetryReadModel.write_seq -> int`` — счётчик принятых PUSH-записей,
    строго растёт; ответ опроса его НЕ двигает.
  * ``TelemetryViewModel.write_seq -> int`` — делегат ядра.
  * ``TelemetryViewModel.ingest_poll_snapshot(values, *, requested_at_seq: int)``
    — ``requested_at_seq`` KEYWORD-ONLY и ОБЯЗАТЕЛЬНЫЙ (без default: умолчание
    позволило бы обойти сторожа молча, просто не передав аргумент). Путь из
    ``values`` отбрасывается, если его последняя PUSH-запись случилась ПОЗЖЕ,
    чем был снят ``requested_at_seq`` (``push_seq[path] > requested_at_seq``).
  * ``TelemetryViewModel.poll_values_dropped_stale -> int`` — счётчик отброшенных
    ПУТЕЙ (не ответов): один ответ с тремя путями может потерять из них один —
    счётчик вырастет на 1, не на 1 «ответ».

Это больше не догадка: имена и семантика зафиксированы координатором дословно.
На HEAD ни ``write_seq``, ни ``requested_at_seq``, ни ``poll_values_dropped_stale``
ещё не существует (реализация пишется параллельно этому файлу) — падение
обязано быть ЯВНЫМ (``AttributeError``/``TypeError`` с понятным текстом через
хелперы ниже), а не тихим. Тело каждого сценария дописано ДО КОНЦА в терминах
итогового контракта, чтобы после появления реализации тест начал судить
ПОВЕДЕНИЕ, а не форму API.

Дыра контракта, замеченная при переписывании (см. отчёт тестера): правило
``push_seq[path] > requested_at_seq`` не различает «push пришёл, ПОКА ответ
летел» (устаревание, законный дроп) и «push пришёл РОВНО в момент отправки
запроса, до как таковой отправки ушёл первый байт» — на границе `==`
(`push_seq[path] == requested_at_seq`) правило ПРИНИМАЕТ ответ опроса (не
`>`, значит не отбрасывается), хотя порядок в проде неопределён (push и
отправка запроса — независимые события, оба могут отметиться одним и тем же
`write_seq`, если между ними не было ДРУГИХ push'ей). Тест B1 сконструирован
так, чтобы push случился СТРОГО ПОСЛЕ снятия `seq` (`seq` снят ДО push'а), то
есть строго проверяет `>`, а не границу `==` — граница описана здесь, а не
проверяется отдельным тестом (недостаточно информации о том, какое поведение
на границе задумано, чтобы писать по ней утверждение, а не догадку).

Как собираются объекты — образец уже закоммиченного `test_telemetry_view_model.py`
(`_delta`, `TelemetryViewModel()` без аргументов).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import (
    TelemetryViewModel,
)


def _delta(path: str, value: object, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


def _write_seq(vm: TelemetryViewModel) -> int:
    """``TelemetryViewModel.write_seq`` — делегат ядра (контракт координатора)."""
    if not hasattr(vm, "write_seq"):
        pytest.fail(
            "Ожидали свойство/атрибут 'write_seq' на TelemetryViewModel (контракт "
            "координатора 2026-08-17: 'счётчик принятых PUSH-записей, строго растёт'). "
            "На HEAD его нет — реализация ещё не появилась, это ожидаемый КРАСНЫЙ."
        )
    value = vm.write_seq
    return value() if callable(value) else value


def _ingest_poll(vm: TelemetryViewModel, values: dict, requested_at_seq: int) -> None:
    """``ingest_poll_snapshot(values, *, requested_at_seq)`` — kw-only и обязательный
    по контракту координатора. ``TypeError`` при отсутствии параметра — законный,
    информативный красный (не догадка, а прямое следствие «параметр обязателен,
    default нет»)."""
    try:
        vm.ingest_poll_snapshot(values, requested_at_seq=requested_at_seq)
    except TypeError as exc:
        pytest.fail(
            "Ожидали 'TelemetryViewModel.ingest_poll_snapshot(values, *, "
            f"requested_at_seq: int)' по контракту координатора (2026-08-17): {exc}. "
            "На HEAD параметра ещё нет — реализация ещё не появилась, это ожидаемый "
            "КРАСНЫЙ, а не опечатка теста."
        )


def _dropped_stale_count(vm: TelemetryViewModel):
    """``poll_values_dropped_stale`` — счётчик отброшенных ПУТЕЙ (контракт координатора)."""
    if not hasattr(vm, "poll_values_dropped_stale"):
        pytest.fail(
            "Ожидали свойство/атрибут 'poll_values_dropped_stale' на TelemetryViewModel "
            "(контракт координатора 2026-08-17: 'счётчик отброшенных ПУТЕЙ'). На HEAD "
            "его нет — реализация ещё не появилась, это ожидаемый КРАСНЫЙ."
        )
    value = vm.poll_values_dropped_stale
    return value() if callable(value) else value


PATH = "processes.cam0.state.probe_level"


# --------------------------------------------------------------------------- #
# B1 — устаревший ответ опроса не воскрешает снятое значение
# --------------------------------------------------------------------------- #
def test_b1_poll_response_sent_before_a_push_none_is_discarded_as_stale(qtbot) -> None:
    vm = TelemetryViewModel()

    seq = _write_seq(vm)  # момент отправки запроса опроса (снят ДО push'а)
    vm.on_state_delta(_delta(PATH, None))  # push прилетел, ПОКА запрос ЛЕТЕЛ (после seq)
    # push обязан был продвинуть write_seq строго вперёд — иначе граница '>' в
    # правиле координатора не может сработать (см. "дыра контракта" в докстринге
    # модуля: тест сознательно бьёт СТРОГО '>', не границу '==').
    assert _write_seq(vm) > seq, (
        "push не продвинул write_seq — предпосылка теста не выполнена (правило "
        "'push_seq[path] > requested_at_seq' не может отличить устаревший ответ "
        "от свежего без строго растущего счётчика PUSH-записей)"
    )

    _ingest_poll(vm, {PATH: 42.0}, requested_at_seq=seq)

    assert vm.get(PATH) is None, (
        f"устаревший ответ опроса (отправлен ДО push'а None) воскресил значение: "
        f"vm.get({PATH!r}) = {vm.get(PATH)!r}, ожидали None"
    )


# --------------------------------------------------------------------------- #
# B2 — обратный порядок не ломается: свежий опрос побеждает
# --------------------------------------------------------------------------- #
def test_b2_poll_response_sent_after_the_push_is_applied(qtbot) -> None:
    vm = TelemetryViewModel()

    vm.on_state_delta(_delta(PATH, None))  # push: значение снято ДО отправки опроса
    seq = _write_seq(vm)  # запрос опроса отправлен ПОСЛЕ push'а

    _ingest_poll(vm, {PATH: 42.0}, requested_at_seq=seq)

    assert vm.get(PATH) == pytest.approx(42.0), (
        f"опрос, отправленный ПОСЛЕ push'а, обязан победить: vm.get({PATH!r}) = {vm.get(PATH)!r}, ожидали 42.0"
    )


# --------------------------------------------------------------------------- #
# B3 — отброшенное учтено числом
# --------------------------------------------------------------------------- #
def test_b3_discarded_stale_poll_values_are_counted_not_silent(qtbot) -> None:
    vm = TelemetryViewModel()

    seq = _write_seq(vm)
    vm.on_state_delta(_delta(PATH, None))
    assert _write_seq(vm) > seq, "push не продвинул write_seq — предпосылка теста не выполнена"

    before = _dropped_stale_count(vm)
    _ingest_poll(vm, {PATH: 42.0}, requested_at_seq=seq)
    after = _dropped_stale_count(vm)

    assert after == before + 1, (
        f"один устаревший путь отброшен, а счётчик расхождения изменился с {before!r} на {after!r} (ожидали ровно +1)"
    )


# --------------------------------------------------------------------------- #
# B4 — судится КАЖДЫЙ путь отдельно, в одном ответе опроса
# --------------------------------------------------------------------------- #
def test_b4_each_path_in_the_same_poll_response_is_judged_independently(qtbot) -> None:
    STALE_PATH = "processes.cam0.state.probe_level_stale"
    FRESH_PATH = "processes.cam0.state.probe_level_fresh"  # без push вообще

    vm = TelemetryViewModel()

    seq = _write_seq(vm)  # ОДИН запрос опроса на оба пути
    vm.on_state_delta(_delta(STALE_PATH, None))  # push пришёл ТОЛЬКО по stale-пути
    assert _write_seq(vm) > seq, "push не продвинул write_seq — предпосылка теста не выполнена"

    _ingest_poll(vm, {STALE_PATH: 999.0, FRESH_PATH: 7.0}, requested_at_seq=seq)

    assert vm.get(STALE_PATH) is None, (
        f"путь с push'ом ПОСЛЕ отправки опроса обязан остаться устаревшим (None), получили {vm.get(STALE_PATH)!r}"
    )
    assert vm.get(FRESH_PATH) == pytest.approx(7.0), (
        f"путь БЕЗ push'а обязан принять значение опроса, получили {vm.get(FRESH_PATH)!r}"
    )


# --------------------------------------------------------------------------- #
# B5 — контроль: ответ опроса не пишет историю
#
# ``requested_at_seq`` обязателен по контракту (нет default) — контрольный тест
# ОБЯЗАН передавать его тоже, иначе он проверял бы вызов, которого в проде не
# бывает (см. пункт координатора «значит и контрольный тест его передаёт»).
# --------------------------------------------------------------------------- #
def test_b5_poll_response_does_not_write_history_control(qtbot) -> None:
    vm = TelemetryViewModel()
    seq = _write_seq(vm)
    _ingest_poll(vm, {"processes.cam0.state.fps": 5.0}, requested_at_seq=seq)
    assert vm.history("processes.cam0.state.fps") == [], (
        "ответ опроса записал точку в кольцо истории — это уже существующее свойство, "
        "которое механизм B не имеет права сломать"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
