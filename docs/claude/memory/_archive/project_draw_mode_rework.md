---
name: project_draw_mode_rework
description: "Доработка режима рисования робота (точность точек, crop, текст/сердце, save/load) — ветка feat/draw-mode-rework, верифицировано тестами, hardware pending"
metadata:
  node_type: memory
  type: project
  originSessionId: 24c6ec05-56ce-4ef7-a7bb-9f8357235b84
---

Ветка `feat/draw-mode-rework` (от checkpoint 5eba0b8b). 6 коммитов, plan `plans/draw-mode-rework/plan.md`.
Доработка режима рисования по 8 пунктам владельца. НЕ смёржена; железная проверка (Lua на роботе,
телефон, mediapipe/TEED-модели) ОТЛОЖЕНА — проверено только тестами (370+ passed) + programmatic.

**Этапы (всё в Plugins/Services, рецепт `multiprocess_prototype/recipes/phone_sketch.yaml`):**
- **A — точность/Стоп/подъём:** эхо-регистр `REG_DRAW_DONE_N=0x1409` + read-back ACK (клиент сверяет
  выполненное с пачкой, повтор/аборт); `draw_pass_size`/`draw_verify`/`draw_retry` в RobotConfig
  (рецепт 30/true/1); `reduce_mode: none` (lossless превью); Стоп=abort+flush+домой; П-образный
  подъём между штрихами через скретч GL_MAN. ADR-RC-006/007/008.
- **B — crop без масштаба:** crop `mode=clip` (нативный масштаб+paste_x/y, обрезка по краю);
  robot_scale `clamp_to_zone` (точка за листом→на границу). Дефолты False, рецепт включает.
- **C — текст/имя/сердце:** новый плагин `Plugins/processing/text_vector` (Hershey-однолинейный
  шрифт: цифры 7-сег + латиница + кириллица А-Я+Ё + параметрич. сердце; матрица 2×2). 2 экземпляра
  в `lines` (text_main/text_name, резолв по class_path, distinct plugin_name), merge=true.
- **D — save/load:** новый плагин `Plugins/io/drawing_io` (JSON+PNG в `drawings/`); load подменяет
  draw_points (превью+робот), прижимает к текущему листу. В `points` index 1 (после robot_scale).

**Корень потери точек (был):** (1) DP-прореживание превью (≠ отправляемое) → reduce_mode none;
(2) тихое усечение в Lua execute_path (`if got<count then count=got`) → read-back ACK ловит.

**Ревью (50 агентов, adversarial):** точки НЕ теряются подтверждено (e2e 2000 точек). Фиксы:
overlap-возобновление длинного штриха (терялся 1 сегмент на границе прохода — связность);
Стоп-между-проходами→домой; re-clamp загрузки; on_progress→snapshot; Ё; честные комментарии.

**Грабли:** [[project_pult_control_panel]] контролы по target_plugin_index — при вставке плагина
в процесс сдвигаются (drawing_io в points сдвинул robot_draw 2→3, обновлён dry_run контрол).
Несколько экземпляров одного плагина = distinct plugin_name + полный plugin_class (резолв по class_path).
Связан с [[project_hikvision_letter_robot]], [[project_robot_vfd_services]], [[project_device_hub]].

**NEXT:** smoke на железе (Lua-прошивка на роботе только там проверяется), merge после боевого теста.
