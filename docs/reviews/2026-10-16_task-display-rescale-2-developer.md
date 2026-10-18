# display-rescale-2 — отчёт developer

STATUS: DONE_WITH_CONCERNS (8 из 9; ac7 краснеет по причине вне DESIGN)

## Итог
display_slot.py правлен строго по DESIGN: `_source_pixmap`, общий `_show_scaled()`, `update_pixmap` и `resizeEvent` масштабируют из исходника, `set_placeholder` сбрасывает исходник до `label.clear()`. Параметры масштабирования прежние.

## Числа
- До правки (соседи + целевой файл): `5 failed, 114 passed` (5 красных = ровно REDS).
- test_display_slot_resize.py после правки: `1 failed, 8 passed` (красный: ac7).
- Соседи + целевой после правки: `1 failed, 118 passed` (новых красных нет; красный один — ac7).

## Почему ac7 красный (корень, не гипотеза)
ac7 (кадр 1000x300, label 700x560) краснеет и БЕЗ ресайза: первый показ даёт отклонение 10.96. Причина: `QPixmap.fromImage(RGB888)` хранит RGB32; сглаживающий скейлер Qt на RGB32 и на RGB888 даёт разные пиксели. Эталон теста считается из исходной QImage RGB888, слот получает только QPixmap (RGB32) -> восстановить RGB888-результат из pixmap невозможно без смены формата.
Замеры (зонд, 1000x300): pixmap.scaled и pixmap.toImage().scaled -> 10.96 (700x560), 0.0 (400x300), 2.45 (900x720). pixmap.toImage().convertToFormat(RGB888).scaled -> 0.0 на всех трёх размерах. RGB32/ARGB32_Premultiplied -> те же 10.96 / 2.45.
Для 640x480 и 800x600 тот же эффект даёт 0.02-1.55 при первом показе; остальные тесты проходят на своих размерах.

## ESCALATION -> teamlead
Question: ac7 требует эталон из RGB888 QImage; DESIGN масштабирует QPixmap (RGB32) -> нужно решение: (A) принять 8/9, ac7 сверх требования владельца «ресайз не портит» (он ловит разницу форматов Qt, не ресайз); (B) в `_show_scaled` масштабировать `source.toImage().convertToFormat(Format_RGB888).scaled(...)` и `QPixmap.fromImage` (по зонду даёт 0.0; но это смена DESIGN, лишнее преобразование на каждый кадр/ресайз и изменение вида первого кадра для всех); (C) поправить эталон теста (тестер).
Tried: DESIGN дословно; зонды выше.
Blocked on: выбор A/B/C (DESIGN и тест — не мои).
Files: multiprocess_prototype/frontend/widgets/image_panel/display_slot.py, .../tests/test_display_slot_resize.py (не правил).

## What I interpreted rather than followed
- Ничего сверх DESIGN. Ранний выход `_show_scaled` при `None`/`isNull()` — прямое прочтение пункта (б).

## What I left open / unreliable
- Вариант B проверен только зондом вне слота, в самом слоте и в тесте не прогонялся.
- Формат кадров из реального presenter (RGB888 или иной) не проверял — вне FILES.
- Хук-форматтер после каждой правки добавляет пустую строку после docstring модуля (строка 2); убрать не удалось (хук возвращает её) — это единственная чужая строка в диффе.

memory hits: search.py display slot rescale pixmap resize -> docs/claude/memory/feedback_display_rescale_must_not_degrade_the_frame.md, feedback_a_source_frame_shape_must_not_crash_the_display.md, project_hikvision_aspect_ratio.md

MEMORY LESSON qpixmap_rgb32_vs_qimage_rgb888_smooth_scale.md:
---
name: qpixmap_rgb32_vs_qimage_rgb888_smooth_scale
description: "QPixmap хранит RGB32, SmoothTransformation на RGB32 и RGB888 даёт разные пиксели (отклонение до 11) / pixmap.scaled does not equal QImage RGB888 .scaled; эталон теста масштабирования"
tags: role: developer; module: prototype; mechanism: gui-display
---
QPixmap.fromImage(RGB888) is stored as RGB32. Qt's smooth scaler gives different pixels for RGB32 and RGB888 (mean abs diff 10.96 for 1000x300 -> 700x210, 0.0 at 400x300). A test reference scaled from an RGB888 QImage cannot equal pixmap.scaled(); convert pixmap.toImage() to RGB888 before scaling, or build the reference from the same pixmap.
