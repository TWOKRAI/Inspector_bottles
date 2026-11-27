registry: defects.md

| C-NN | **Чек-лист дня №1 устарел: велит писать кадры после `color_convert`, а рецепты камеры уже без этой ноды (камера отдаёт BGR)** — `docs/handoffs/2026-11-15_day1-camera-checklist.md` §4.3 против `multiprocess_prototype/recipes/hikvision_inspect.yaml` (шапка) и `hikvision_letter_robot.yaml` (раздел «ЦВЕТ»); сборка по чек-листу дала бы переставленные R и B (вывод из текстов, не замер). Порядок каналов на приборе не проверен (визит 6.3). Рецепт записи в git отсутствует и ни разу не загружался | чтение 2026-11-27, полоса С1 layer-render | открыто; **до дня №1** |
