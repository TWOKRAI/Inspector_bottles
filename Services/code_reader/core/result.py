# -*- coding: utf-8 -*-
"""Разбор результата чтения, приходящего от считывателя ID3000.

Формат снят с прибора MV-ID3013PM-06M-SENSOTEC (прошивка V4.0.2.C 251201),
а не взят из мануала — в мануале ID3000 раздела «Set Result Format» нет.
Живой пакет по TCP Client:

    QR-30MM;   ->   51 52 2D 33 30 4D 4D 3B

Суффикс — хвост строки формата `TCP Client Output Format String` (у нас
``<code_content>;``), префикс — её начало. Тексты неудачи (NoRead) через строку
формата НЕ идут: терминатор прибор к ним не добавляет, он должен стоять в самом
тексте (снято 2026-09-29, `docs/SETUP.md` раздел 5). CR/LF и STX/ETX прибор не добавляет, но у другого
экземпляра или прошивки они могут быть, поэтому разбор их терпит.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class ReadStatus(str, Enum):
    """Исход одного срабатывания триггера."""

    OK = "ok"
    """Код прочитан."""

    NO_CODE = "no_code"
    """Кода в кадре не нашлось — `TCP Client Output NoRead Text`."""

    BAD_CODE = "bad_code"
    """Код найден, но не декодирован — `TCP Client Output With Code NoRead Text`.

    Работает, когда включён `With Code But NoRead Check Enable`. Смысл параметра
    в мануалах ID3000 не описан (он в отдельном IDMVS Client Software User Manual)
    и на нашем экземпляре ещё не проверен — см. STATUS.md.
    """


@dataclass(frozen=True)
class ReadResult:
    """Одно срабатывание: что пришло и как это трактовать."""

    raw: bytes
    """Исходные байты пакета — источник истины при разборе спорных случаев."""

    payload: str
    """Содержимое без префикса и суффикса."""

    status: ReadStatus

    @property
    def is_good(self) -> bool:
        return self.status is ReadStatus.OK

    def to_dict(self) -> dict:
        """Dict at Boundary: между процессами уходит dict, не dataclass."""
        data = asdict(self)
        data["raw"] = self.raw.hex(" ").upper()
        data["status"] = self.status.value
        return data


def parse_packet(
    data: bytes,
    *,
    terminator: str = ";",
    prefix: str = "",
    no_code_text: str = "NoRead",
    bad_code_text: str | None = None,
) -> ReadResult:
    """Разобрать один пакет от считывателя.

    Args:
        data: сырые байты ровно одного результата (без склейки).
        terminator: хвост `TCP Client Output Format String` прибора.
        prefix: начало строки формата; пустой, если не задан.
        no_code_text: `Output NoRead Text` — «кода нет».
        bad_code_text: `Output With Code NoRead Text` — «код есть, не читается».
            None означает, что различение выключено и оба случая придут как
            `no_code_text`.

    Разделение двух видов неудачи работает только когда тексты **разные**.
    Заводское умолчание прибора — оба текста ``NoRead``; тогда недостижим
    `bad_code`, а всё пустое идёт в `no_code`. Это настройка прибора, а не дефект
    разбора, и порядок проверок ниже выбран так, чтобы совпадение текстов давало
    именно `no_code`: «кода нет» — точная и безопасная трактовка, а «код есть, но
    не читается» при неотличимых текстах была бы догадкой. Ревью Ф2 нашло
    обратный порядок — пустые срабатывания уходили в `bad_code`, и счётчик «кода
    нет» вечно стоял на нуле.

    Пустой результат (пришёл только терминатор) — тоже `no_code`: успешного
    чтения с пустым кодом не бывает, а проглотить такой пакет молча значит
    потерять срабатывание.
    """
    text = data.decode("utf-8", errors="replace")
    # Управляющие обрамления и перевод строки прибор не шлёт, но чужая
    # конфигурация может — снимаем их до сравнения с текстами NoRead.
    text = text.strip("\x02\x03\r\n")
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :]
    if terminator and text.endswith(terminator):
        text = text[: -len(terminator)]

    if not text or text == no_code_text:
        # Порядок важен: no_code проверяется ПЕРВЫМ, поэтому при совпадающих
        # текстах (заводская настройка) срабатывание считается «кода нет».
        status = ReadStatus.NO_CODE
    elif bad_code_text and text == bad_code_text:
        status = ReadStatus.BAD_CODE
    else:
        status = ReadStatus.OK
    return ReadResult(raw=data, payload=text, status=status)


def split_stream(buffer: bytes, terminator: str = ";") -> tuple[list[bytes], bytes]:
    """Нарезать поток на пакеты по терминатору.

    TCP не сохраняет границы сообщений: два быстрых чтения могут прийти одним
    recv, а одно — двумя. Возвращает завершённые пакеты и остаток, который надо
    дописать к следующему куску.

    Пустой `terminator` означает «границ нет» — тогда всё уходит в остаток, и
    резать поток должен вызывающий (например по паузе). Готового способа резать
    по паузе в сервисе нет, поэтому плагин пустой терминатор отвергает: приём с
    ним копил бы поток в памяти и не отдавал ни одного кода.

    Пакет «только терминатор» (пустая полезная часть) возвращается наравне с
    остальными: это срабатывание с пустым результатом, а не мусор. Раньше фильтр
    его выбрасывал — молчаливая потеря, найденная ревью Ф2.
    """
    if not terminator:
        return [], buffer

    sep = terminator.encode("utf-8")
    parts = buffer.split(sep)
    tail = parts.pop()
    return [part + sep for part in parts], tail
