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

### Аналитика выбора компонентов

| Файл | Содержание |
|------|-----------|
| [ANALYSIS_MCU.md](ANALYSIS_MCU.md) | Подробный анализ MCU: ESP32-S3, STM32, Teensy, ROS Board |

## Конфигурация в двух словах

```
Уровень 1: Jetson Orin NX 16GB (YAHBOOM)    — LLM + голос + планирование
Уровень 2: Jetson Orin Nano 8GB (STEMBLOCK) — SLAM + навигация + сенсоры глубины
Уровень 3: RPi 5 8GB + AI HAT+              — компьютерное зрение (YOLO на Hailo-8)
Уровень 4: ROS Board + ESP32-S3             — моторы, сервы, энкодеры, аварийный стоп
```
