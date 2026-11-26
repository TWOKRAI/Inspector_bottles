# H9 — камера MVS не называет себя driver: fake

- **Суть:** `HikvisionCameraRegisters` наследовал умолчание базы `driver: fake`.
- **Итог:** умолчание `mvs` (`fcccd8501`); базовый регистр не менялся.
- **Проверка:** красный до правки `'fake' == 'mvs'`; интроспекция через настоящий оркестратор даёт `mvs`; ревью APPROVED.
- **Проблемы:** каталог `Services/hikvision_camera/tests` ревьюер не прогнал (чужое окно); у автора 366 passed, 4 skipped.
- **Агенты:** developer `a33531db02ea423dc`, reviewer `a8cc3c5248ff7891a` (sonnet).
- **Открыто:** `driver` можно перезаписать конфигом, порт всё равно `mvs`; `source_type="simulator"` из F5 не исправлен;
  `test_catalog_kind_roundtrip` красный и без этой правки (два поля `robot_io` вне снимка).
- **Дальше:** на приборе не проверялось.
