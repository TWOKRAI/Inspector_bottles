---
name: feedback_a_source_frame_shape_must_not_crash_the_display
description: "Серый кадр источника (image/gray) убил процесс gui без трейсбека (0xC0000005); image_panel/on_frame читал любой кадр как 3-канальный BGR; нативное падение не видно в логах — нужен faulthandler; кадр не шёл на дисплей, пока рецепт не перезагрузили"
module: [prototype/frontend, services/code_reader]
mechanism: [live-stand, qt, error-handling]
metadata:
  type: feedback
---

Владелец (2026-10-15): это рушит идею конструктора — любой источник из рецепта должен показываться на дисплее одним надёжным механизмом, а не падать из-за формы кадра. Источник сравнения — `Services/hikvision_camera` в рецепте с буквами (`hikvision_letter_robot.yaml`): там кадр идёт BGR через узел `color_convert`.

**Что случилось.** Рецепт `qr_reader_sdk_demo` привязал порт `frame` (`image/gray`, 1024×1280, 1 канал) к дисплею. Процесс `gui` умирал `exitcode=3221225477` (0xC0000005) сразу на первом кадре, окно закрывалось «после триггера». `format: GRAY` в рецепте не помогал.

**Причина (по faulthandler, `multiprocess_prototype/frontend/widgets/image_panel/presenter.py::on_frame`).** Ветка считала любой кадр BGR: `frame[..., ::-1]`, `bytes_per_line = 3*w`, `QImage(..., Format_RGB888)`. На серый буфер w*h байт Qt читал 3*w*h — чтение за границей. Поле `format` дисплея там не используется (в `preview_window.py` GRAY есть, в `image_panel` не было). Исправлено: 2-D и (H,W,1) → `Format_Grayscale8`, 3 канала → прежняя ветка, остальное → placeholder «Ошибка кадра»; тесты `image_panel/tests/test_on_frame_shapes.py`.

**Почему это долго искали.** Нативное падение не пишется в логи процесса: в наблюдаемости только `ProcessManager: gui crashed exitcode=…` и следствие (переполнение очереди `gui.state`, 17+ предупреждений), от самого `gui` — 0 записей WARNING+. `faulthandler` в `frontend/app.py` включается только флагом `INSPECTOR_STALL_DUMP=1` и только для зависаний. Нашлось запуском с `PYTHONFAULTHANDLER=1 python -X faulthandler …` (вывод родителя).

**Открыто (в план, не сделано):**
- Включать `faulthandler` в `process_runner` для каждого процесса в его лог-каталог, а supervisor — ссылаться на этот файл в строке `crashed`.
- После старта стенда кадр не шёл на дисплей, пока владелец не активировал рецепт заново (`RecipeActivated qr_reader_demo` → `routing={}` → `qr_reader_sdk_demo` → `routing={'reader_sdk':'main'}`); в карточке рецепта «Дисплеи: 0» при одной привязке. Порядок инициализации дисплея и подписки на кадр — не разобран.
- Проверка форм кадров на входе дисплея (контракт `image/gray` ↔ `image/bgr`) — один механизм для всех источников.

**How to apply:** падение процесса без трейсбека и `exitcode=3221225477` → сразу `PYTHONFAULTHANDLER=1`, смотреть `Current thread` внизу вывода; новый источник кадров в рецепте → проверить, что GUI принимает его форму (gray/bgr) и что кадр идёт сразу после старта, а не после перезагрузки рецепта. См. [[reference_idmvs_gev_reader_needs_encryption_key]].
