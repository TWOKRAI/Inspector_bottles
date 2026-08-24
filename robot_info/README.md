# Robot Project — База знаний

Документация и проектирование многоуровневой робототехнической системы.

## Структура

| Файл | Содержание |
|------|-----------|
| [HARDWARE.md](HARDWARE.md) | Инвентаризация оборудования (есть / нужно купить) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 4-уровневая архитектура системы |
| [COMMUNICATION.md](COMMUNICATION.md) | Протоколы связи между уровнями |
| [SOFTWARE_STACK.md](SOFTWARE_STACK.md) | Софт на каждом уровне (ОС, фреймворки, модели) |
| [SOFTWARE_ARCHITECTURE.md](SOFTWARE_ARCHITECTURE.md) | Архитектура ПО: единый фреймворк на всех уровнях + клиенты (ПК, телефон) |
| [TODO.md](TODO.md) | Что нужно докупить, решить, исследовать |
| [ASSISTANT_VISION.md](ASSISTANT_VISION.md) | Настольный голосовой ассистент («Jarvis») — концепция, сценарии, MCP-архитектура, стол как интерактивная поверхность |

### Аналитика выбора компонентов

| Файл | Содержание |
|------|-----------|
| [Analysis/ANALYSIS_MCU.md](Analysis/ANALYSIS_MCU.md) | MCU: ESP32-S3, STM32, Teensy, ROS Board |
| [Analysis/ANALYSIS_DEPTH_CAMERA.md](Analysis/ANALYSIS_DEPTH_CAMERA.md) | Depth-камера: Orbbec 335/335L/336/336L/Astra, RealSense, OAK-D. Расчёт точности на близкой дистанции, сценарий 3D-инспекции |
| [Analysis/ANALYSIS_POWER.md](Analysis/ANALYSIS_POWER.md) | Питание и охлаждение: энергобюджет, шина 12 В против 24 В, выбор БП, вентиляторы, тепловые зоны |
| [Analysis/ANALYSIS_NETWORK.md](Analysis/ANALYSIS_NETWORK.md) | Внутренняя сеть: гигабит, магнетики, выбор свитча, DHCP/NTP, верификация |
| [Analysis/ANALYSIS_MANIPULATOR.md](Analysis/ANALYSIS_MANIPULATOR.md) | Манипулятор (Фаза 4): SO-101, приводы STS3215, энергобюджет, частота контура, промышленная адаптация под Delta/SCARA/KUKA, доступность моделей |
| [Analysis/ANALYSIS_CONVEYOR.md](Analysis/ANALYSIS_CONVEYOR.md) | Мини-конвейер 600×220: лента, мотор, два энкодера, смаз и триггер камеры, контракт с `line_sim` |

> В аналитических документах используется разметка достоверности:
> **[П]** проверено по источнику · **[Р]** расчёт с явными допущениями · **[О]** оценка,
> не измерено. Разделение введено 2026-08-02 — чтобы через полгода было видно,
> что факт, а что суждение.

## Конфигурация в двух словах

```
Уровень 1: Jetson Orin NX 16GB (YAHBOOM)    — LLM + голос + планирование
Уровень 2: Jetson Orin Nano 8GB (STEMBLOCK) — SLAM + навигация + сенсоры глубины
Уровень 3: RPi 5 8GB + AI HAT+              — компьютерное зрение (YOLO на Hailo-8)
Уровень 4: ROS Board + ESP32-S3             — моторы, сервы, энкодеры, аварийный стоп
```
