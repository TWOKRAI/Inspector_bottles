# -*- coding: utf-8 -*-
"""
Fencing-token: штамп конверта incarnation/epoch + drop stale на приёме (Ф4.2).

Требование владельца (2026-07-08): после `topology switch` старый процесс НЕ должен
вкинуть stale-сообщение в новую топологию. `incarnation`/`epoch` уже существуют
(ADR-PMM-010, Ф3.1), но применяются лишь к CLEANUP очередей и к самому
`routing.refresh`. Здесь — жёсткий барьер: штамповать каждое control-plane сообщение
и отбрасывать на приёмнике то, у которого epoch отстал от известного получателю.

Две ЧИСТЫЕ фабрики (не знают про `RouterManager`), совместимые с
:meth:`add_send_middleware` / :meth:`add_receive_middleware`. Провайдеры
epoch/incarnation (чтение PSR / PM-истины) и флаг ``FW_FENCE`` — забота композиции
(проводки в процессе), не этого модуля.

**Ключ дропа — per-sender ``incarnation``, НЕ глобальный ``epoch``** (урок live-e2e,
см. ADR-PMM-014). Требование владельца буквально: «у каждого процесса свой id;
старые процессы не вкидывают в новую топологию». Старый процесс = устаревший
*incarnation* (его заменил новый инстанс с incarnation+1 — ``_bump_incarnation`` в PM
при restart/provision), а НЕ «отставший по глобальному epoch». Получатель знает
текущий incarnation каждого соседа из ``routing.refresh``
(``PSR[sender].metadata["routing_incarnation"]``) и дропает билет, чей ``inc`` меньше.
Так фильтр НЕ трогает легитимный текущий процесс, даже если тот отстал по epoch
(эпоха-based критерий ложно дропал state/telemetry в переходном окне после switch).
``epoch`` штампуется для диагностики и будущего (Ф4.9 — тот же монотонный счётчик).

Инварианты:
  - **Только control-plane.** Data-plane (кадры: ``type=="data"`` или
    ``use_shared_memory``) НЕ штампуется и НЕ фильтруется — горячий путь,
    сознательное решение ADR-PMM-010; перенос на data-plane — Ф7 G.4 под флагом.
  - **Fail-open.** Если у получателя нет известного incarnation отправителя
    (провайдер вернул ``None`` — неизвестный процесс) или штамп неполон — НЕ дропать.
    На отправке: пока свой incarnation неизвестен — НЕ штамповать (легаси-проход).
  - **Обратная совместимость.** Сообщение без ``_fence`` проходит фильтр прозрачно.

Дизайн-документ фазы: `plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md`.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

# Ключ fence-конверта в transport-dict сообщения. Nested (не top-level поле
# `Message`), чтобы не течь в payload-схемы контрактов и не менять `message.py`.
# `_`-префикс роднит его с прочими transport-ключами (`_address`, `_receive_info`,
# `_source_channel`, `_relayed`) — реестр контрактов их исключает из `unexpected`.
FENCE_KEY = "_fence"

# Короткие ключи внутри fence-конверта (уходят в каждый control-plane билет).
_F_SENDER = "sender"
_F_INCARNATION = "inc"
_F_EPOCH = "epoch"

# Провайдеры, внедряемые композицией:
#   FenceProvider       → (own_incarnation | None, own_epoch | None) для штампа отправителя;
#   IncarnationProvider → (sender) → known_incarnation | None — известный получателю
#                         текущий incarnation отправителя (из PSR соседа).
FenceProvider = Callable[[], Tuple[Optional[int], Optional[int]]]
IncarnationProvider = Callable[[str], Optional[int]]
MiddlewareFn = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
DropHook = Callable[[Dict[str, Any]], None]


def is_data_plane(message: Dict[str, Any]) -> bool:
    """True для кадров data-plane (горячий путь) — их fence НЕ трогает."""
    return message.get("type") == "data" or bool(message.get("use_shared_memory"))


def read_fence(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """fence-конверт сообщения или ``None`` (нет штампа / кривой тип)."""
    fence = message.get(FENCE_KEY)
    return fence if isinstance(fence, dict) else None


def make_fence_stamp_middleware(sender: str, get_fence: FenceProvider) -> MiddlewareFn:
    """Собрать send-middleware, штампующий control-plane исходящие полем ``_fence``.

    Штамп ставится, ТОЛЬКО когда свой ``incarnation`` известен (провайдер вернул
    не-``None`` incarnation) — иначе сообщение уходит нештампованным (легаси-проход,
    fail-open): без incarnation получатель не сможет решить про stale. ``epoch``
    штампуется для диагностики (может быть ``None``). Data-plane пропускается без
    изменений (горячий путь). Провайдер, бросивший исключение, не роняет отправку.
    """

    def _stamp(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if is_data_plane(message):
            return message
        try:
            incarnation, epoch = get_fence()
        except Exception:  # noqa: BLE001 — провайдер не должен ронять send
            return message
        if incarnation is None:
            return message  # свой incarnation неизвестен → не штампуем (fail-open)
        message[FENCE_KEY] = {
            _F_SENDER: sender,
            _F_INCARNATION: incarnation,
            _F_EPOCH: epoch,
        }
        return message

    return _stamp


def make_fence_filter_middleware(
    get_expected_incarnation: IncarnationProvider,
    *,
    on_drop: Optional[DropHook] = None,
) -> MiddlewareFn:
    """Собрать receive-middleware, дропающий билет от УСТАРЕВШЕГО инстанса отправителя.

    Дроп (``return None``), если у сообщения есть ``_fence`` с ``sender``/``inc`` и
    ``inc`` меньше известного получателю текущего incarnation этого отправителя
    (``PSR[sender].routing_incarnation``) — т.е. билет прислал СТАРЫЙ инстанс,
    заменённый новым. Проходит прозрачно: сообщение без ``_fence``, с ``inc`` ``>=``
    известного, или когда получатель не знает incarnation отправителя (fail-open —
    неизвестный/нештампованный процесс). Текущий инстанс НЕ дропается, даже если
    отстал по глобальному epoch (в этом отличие от эпоха-based: тот ложно дропал
    легитимный state/telemetry в переходном окне после switch — см. ADR-PMM-014).
    Data-plane не фильтруется. ``on_drop`` — для fence-специфичного счётчика.
    """

    def _filter(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if is_data_plane(message):
            return message
        fence = read_fence(message)
        if fence is None:
            return message  # легаси/без штампа — прозрачно
        sender = fence.get(_F_SENDER)
        msg_inc = fence.get(_F_INCARNATION)
        if not isinstance(sender, str) or not isinstance(msg_inc, int):
            return message  # неполный штамп — не дропаем (fail-open)
        try:
            expected = get_expected_incarnation(sender)
        except Exception:  # noqa: BLE001 — провайдер не должен ронять receive
            return message
        if not isinstance(expected, int):
            return message  # получатель не знает incarnation отправителя → fail-open
        if msg_inc < expected:
            if on_drop is not None:
                try:
                    on_drop(message)
                except Exception:  # noqa: BLE001 — счётчик/лог не роняет приём
                    pass
            return None  # DROP: билет от устаревшего инстанса (заменён новым)
        return message

    return _filter


__all__ = [
    "FENCE_KEY",
    "FenceProvider",
    "IncarnationProvider",
    "MiddlewareFn",
    "DropHook",
    "is_data_plane",
    "read_fence",
    "make_fence_stamp_middleware",
    "make_fence_filter_middleware",
]
