# -*- coding: utf-8 -*-
"""Task 2.4 — граница инкарнации: gen под локом + честное возобновление.

Две находки ultra-ревью в одном месте:

1. **TOCTOU на поколении.** ``_parse_cursor`` читал ``self._gen`` СНАРУЖИ ``self._cv``,
   а страница бралась уже под локом. В окне между проверкой и чтением ``emit()``
   успевал ротировать поколение (наблюдаемый процесс пересёк рестарт) — курсор
   валидировался против старого gen, а данные и штамп ``next_cursor`` приезжали из
   нового. Читатель молча проезжал границу инкарнации: ровно та слепота, ради которой
   B.1 и вводил generation-токены.

2. **reset вываливал весь ринг заново.** Ответ ``reset_required`` предлагал только
   «начни с cursor=null», то есть перечитать ВСЁ доступное — включая то, что читатель
   уже видел до рестарта. Регресс против удалённого ``drain()``. Теперь ответ несёт
   ``resume_cursor`` — точку границы, с которой идут ТОЛЬКО события новой инкарнации.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from backend_ctl.events import ALL_PLANE, EventHub


def _restart_push(process: str = "camera_0") -> Dict[str, Any]:
    """Push, который hub опознаёт как границу рестарта (supervisor recovered)."""
    return {
        "command": "state.changed",
        "data": {"deltas": [{"path": f"processes.{process}.supervisor.event", "new_value": "recovered"}]},
    }


def _plain_push(n: int) -> Dict[str, Any]:
    return {"command": "log.record", "data": {"n": n}}


# --- Возобновление с границы, а не с начала ---


def test_reset_after_rotation_offers_resume_cursor() -> None:
    """Курсор старого поколения → reset_required с точкой возобновления."""
    hub = EventHub(maxlen=100)
    hub.emit(_plain_push(1))
    hub.emit(_plain_push(2))
    page = hub.page(ALL_PLANE)
    old_cursor = page["next_cursor"]

    hub.emit(_restart_push())  # ротация поколения

    reset = hub.page(ALL_PLANE, cursor=old_cursor)
    assert reset["success"] is False
    assert reset["reset_required"] is True
    assert "resume_cursor" in reset, "ответ обязан назвать точку возобновления, а не только «начни заново»"


def test_resume_cursor_returns_only_new_incarnation() -> None:
    """Повтор по resume_cursor отдаёт ТОЛЬКО события после рестарта.

    До Task 2.4 восстановление шло с ``cursor=null`` и вываливало весь доступный ринг —
    всё, что читатель уже видел до рестарта, приезжало по второму разу.
    """
    hub = EventHub(maxlen=100)
    for i in range(3):
        hub.emit(_plain_push(i))  # «старая жизнь» — читатель это уже видел
    old_cursor = hub.page(ALL_PLANE)["next_cursor"]

    hub.emit(_restart_push())
    for i in range(100, 103):
        hub.emit(_plain_push(i))  # новая инкарнация

    reset = hub.page(ALL_PLANE, cursor=old_cursor)
    resumed = hub.page(ALL_PLANE, cursor=reset["resume_cursor"])

    assert resumed["success"] is True
    payloads = [it["event"]["data"]["n"] for it in resumed["items"] if it["event"].get("command") == "log.record"]
    assert payloads == [100, 101, 102], f"ожидались только события новой инкарнации, пришло {payloads}"

    # Контроль: полное перечитывание (прежнее поведение) отдало бы и старое.
    full = hub.page(ALL_PLANE, cursor=None)
    full_payloads = [it["event"]["data"]["n"] for it in full["items"] if it["event"].get("command") == "log.record"]
    assert 0 in full_payloads, "контроль: с начала ринга старые события ещё доступны"


def test_no_boundary_yet_means_no_resume_cursor() -> None:
    """Рестартов не было → возобновляться не с чего, ключа нет (откат на полное чтение)."""
    hub = EventHub(maxlen=100)
    hub.emit(_plain_push(1))

    reset = hub.page(ALL_PLANE, cursor="all:999@чужое")
    assert reset["success"] is False
    assert "resume_cursor" not in reset


# --- TOCTOU: проверка поколения и чтение — одна атомарная операция ---


def test_no_success_page_stamped_with_rotated_generation() -> None:
    """Под ротацией из другого потока ни одна успешная страница не смешивает поколения.

    Инвариант: gen в ``next_cursor`` успешного ответа совпадает с gen, против которого
    курсор был проверен. Раньше проверка и штамп брали ``self._gen`` в разные моменты.
    """
    hub = EventHub(maxlen=500)
    hub.emit(_plain_push(0))

    stop = threading.Event()
    mismatches: List[str] = []

    def _rotator() -> None:
        while not stop.is_set():
            hub.emit(_restart_push())
            hub.emit(_plain_push(1))

    def _reader() -> None:
        cursor: Any = None
        while not stop.is_set():
            page = hub.page(ALL_PLANE, cursor=cursor)
            if page.get("success"):
                nxt = page["next_cursor"]
                # Успешная страница обязана быть выдана в поколении своего курсора:
                # если курсор был не None, его gen обязан совпасть с gen ответа.
                if cursor is not None and cursor.rpartition("@")[2] != nxt.rpartition("@")[2]:
                    mismatches.append(f"курсор {cursor} → страница {nxt}")
                cursor = nxt
            else:
                cursor = page.get("resume_cursor")

    threads = [threading.Thread(target=_rotator), threading.Thread(target=_reader)]
    for t in threads:
        t.start()
    threading.Event().wait(1.0)
    stop.set()
    for t in threads:
        t.join(timeout=5.0)
    assert not [t for t in threads if t.is_alive()], "поток завис — вероятен дедлок на _cv"

    assert not mismatches, f"страница выдана в чужом поколении: {mismatches[:3]}"


def test_page_is_consistent_under_concurrent_emit() -> None:
    """Параллельные emit во время чтения не рвут страницу и не роняют hub."""
    hub = EventHub(maxlen=1000)
    stop = threading.Event()
    errors: List[BaseException] = []

    def _writer() -> None:
        i = 0
        while not stop.is_set():
            hub.emit(_plain_push(i))
            i += 1

    def _reader() -> None:
        cursor: Any = None
        try:
            while not stop.is_set():
                page = hub.page(ALL_PLANE, cursor=cursor)
                if page.get("success"):
                    seqs = [it["seq"] for it in page["items"]]
                    assert seqs == sorted(seqs), "страница пришла с нарушенным порядком seq"
                    cursor = page["next_cursor"]
                else:
                    cursor = page.get("resume_cursor")
        except BaseException as exc:  # noqa: BLE001 — падение читателя обязано валить тест
            errors.append(exc)

    threads = [threading.Thread(target=_writer), threading.Thread(target=_reader)]
    for t in threads:
        t.start()
    threading.Event().wait(1.0)
    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert not errors, f"читатель упал: {errors[0]!r}"
