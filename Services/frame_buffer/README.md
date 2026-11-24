# Services/frame_buffer

Кольцо сжатых кадров в RAM с доступом «кадр на момент t», закреплением диапазона и экспортом в формате сегмента
(блок независимых JPEG + индекс фиксированной длины). Имя пакета — решение владельца 12, подтверждения нет.

**Stability: lite.** `interface.py` не заводится: один класс, одна реализация. Контракт — этот README и тесты.

## Purpose

- Хранить кадры за последние `buffer_seconds` секунд под жёстким потолком `max_bytes`: окно считает секунды, не штуки.
- Отдать кадр на момент `t` (`at`), диапазон и разрывы нумерации (`range`), счётчики (`stats`).
- Закрепить диапазон вокруг события (`pin`), найти кадры группы (`find_group`), выгрузить диапазон (`export`)
  в том же виде, что пойдёт на диск (T12).

## Public API

Экспорт `Services/frame_buffer/__init__.py`: `TimeRing`, `read_segment`.

- `TimeRing(buffer_seconds, max_bytes, pin_max_bytes)` — без значений по умолчанию (ждут замера настоящих кадров);
  `pin_max_bytes <= max_bytes`, иначе `ValueError`.
- `append(capture_ns, capture_ts, payload, seq, device_frame_num=None, group_id=None, flags=0)` — один писатель.
  `flags & 0b11` -> `ValueError` (биты 0 и 1 зарезервированы форматом; пользовательские — биты 2..31).
  Также `ValueError`: `capture_ns`, `seq`, `device_frame_num`, `group_id` вне i64 или не целые; `capture_ts` не число
  (число хранится как `float`). Текст без значения входа, кольцо при отказе не меняется.
- `at(t_ns, mode)` -> `dict | None` с ключами `payload` (bytes без копии), `capture_ns`, `capture_ts`, `seq`,
  `device_frame_num`, `group_id`, `flags`. `mode`: `prev` — последний с `capture_ns <= t`, `next` — первый с
  `capture_ns >= t`, `nearest` — ближайший, при равенстве расстояний `prev`.
- `range()` -> `{"t_min_ns", "t_max_ns", "frames", "gaps"}`; пустое кольцо: `None`, `None`, `0`, `[]`.
  Разрыв: `{after_seq, before_seq, missed, capture_ns, restart}`; рестарт `seq` — `restart: True`, `missed: 0`.
- `stats()` -> `{frames, bytes_held, bytes_held_peak, span_s, evicted_by_time, evicted_by_bytes, rejected_order,
  rejected_oversize, pins_released}`; `range()["frames"] == stats()["frames"]`.
- `pin(t0_ns, t1_ns, tag)` / `unpin(tag)` — закрепление интервала (включающий), в том числе будущих кадров.
- `find_group(group_id)` -> `list[dict]` в порядке `(capture_ns, seq)`.
- `export(t0_ns, t1_ns)` -> `{"blob": bytes, "index": bytes}`; пустой диапазон — пустые `blob` и `index`;
  `t0 > t1` -> `ValueError`.
- `read_segment(blob, index)` -> `list[dict]` тех же ключей; устойчив к обрезанному блоку и индексу.
- `segment.build_segment(frames)` -> `(blob, index)`; `segment.RECORD` — `struct "<QIqdqqqI"`, 56 байт.

## Инварианты

- Порядок кольца — пара `(capture_ns, seq)`; отвергается (`rejected_order`) кадр с парой не больше последней принятой.
- Вытеснение по времени строго `capture_ns < newest - buffer_ns` (граница включающая), затем по байтам, всегда
  самого старого незакреплённого; место освобождается ДО вставки: `bytes_held <= max_bytes` всегда.
- Кадр больше `max_bytes` отвергается (`rejected_oversize`), кольцо не трогается.
- Закреплённые байты не больше `pin_max_bytes`; иначе освобождается самый старый пин (`pins_released`).
  Закреплённые байты ведёт счётчик (пересчёт при `pin`, `unpin`, освобождении), не скан на каждый `append`.
- Один писатель, читатели под замком; `export` склеивает блок вне замка. Слои: пакет не импортирует Qt,
  `multiprocess_framework`, Plugins и прототип.

## Stability

Stability: lite

## Решения и план

- [`DECISIONS.md`](DECISIONS.md) — ADR-RING-001 (вытеснение), ADR-RING-002 (формат), ADR-RING-003 (закрепление).
- План: [`plans/2026-11-24_gui-frame-path/plan.md`](../../plans/2026-11-24_gui-frame-path/plan.md); `STATUS.md` — после T9b.
