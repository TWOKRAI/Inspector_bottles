# STATUS — Services.phone_gateway

**Состояние:** v1 готов — always-on сервис с тумблером в GUI, проверен вживую.

## Готово

- [x] `gateway.py` — HTTP-сервер (stdlib, фоновый поток) + хранилище фото/слова + toggle (start/stop)
- [x] `imaging.py` — decode (EXIF-поворот, dependency-free) + letterbox
- [x] `netinfo.py` — определение локального IP · `qr.py` — QR URL/WiFi (SVG+PNG, опц. segno)
- [x] `web.py` — HTML-страница (фото + слово/фраза)
- [x] `plugin/` — PhoneCameraPlugin (source, `phone_camera`) + команды start_server/stop_server/server_status
- [x] always-on процесс `phone_gateway` в `base.yaml` (protected, `auto_start: false`)
- [x] GUI: секция **Services → Телефон** — тумблер Вкл/Выкл + URL + QR + последнее слово + подсказка
- [x] приём **фразы из нескольких слов** (внутренние пробелы сохраняются)
- [x] 27 тестов Service + 3 GUI-секции; 127 существующих (recipes/assembly/services) не сломаны

## Проверено вживую (qt-mcp + curl)

- Панель рендерится: URL `http://<IP>:8080/` (вычислен локально), QR-плейсхолдер (segno нет)
- Тумблер «Включить» → команда через bridge → сервер up (200 /health) → статус «включён ✓» реактивно
- `POST /word "ГАЙКА"` → state → GUI-метка «Последнее слово: ГАЙКА» (кросс-процессно)
- `POST /frame` 640×480 → 200; кадры идут до GUI (`on_frame slot 'main'`)

## Дизайн-решения

- **Сервис, не камера:** always-on процесс в base.yaml, сервер toggle из Services-вкладки.
- **Режим:** дискретный снимок, `hold_last=True`. **Транспорт:** WiFi + браузер.
- **SHM-слот** `camera_9_frame` (не конфликтует с `camera_0` рецепта).
- **letterbox** (без искажений) + **EXIF-поворот**. **Слово → state** `phone.word`.
- Сервер живёт в процессе-источнике (фото = SHM-кадр, не гонять по шине).

## TODO (follow-up)

- [ ] Прокинуть `phone.word` в сам распознаватель букв («другой режим»)
- [ ] Маршрут фото в обработку рецепта (сейчас источник → gui; инспекция = recipe wiring)
- [ ] (опц.) HTTPS/самоподписанный сертификат — если телефон блокирует камеру в браузере по HTTP
- [ ] (опц.) WiFi-QR в GUI (нужны SSID+пароль) · segno в extras pyproject

## Smoke

`python multiprocess_prototype/run.py <любой рецепт>` → Services → Телефон → «Включить»
→ открыть `http://<IP>:8080` на телефоне → отправить фото/слово.
