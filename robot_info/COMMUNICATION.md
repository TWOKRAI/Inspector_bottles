# Communication — Протоколы связи между уровнями

## Общая схема

```
  Уровень 1              Уровень 2              Уровень 3
┌──────────┐          ┌──────────┐          ┌──────────┐
│ Orin NX  │◄──ETH───►│  Nano    │◄──ETH───►│  RPi 5   │
│  16GB    │  ROS2    │  8GB     │  ROS2    │  8GB     │
└──────────┘  DDS     └──────────┘  DDS     └──────────┘
                           │                      │
                           │ USB                  │
                      ┌────▼─────┐           ┌────▼─────┐
                      │ RPLIDAR  │           │ RPi Cam  │
                      │ D435i    │           │          │
                      └──────────┘           └──────────┘
                           │
                      UART/USB (rosserial)
                           │
                      ┌────▼─────┐
                      │ Arduino  │  Уровень 4
                      │ Mega     │
                      └──────────┘
```

## Связи между уровнями

### Уровень 1 ↔ Уровень 2: Ethernet + ROS2 DDS

| Параметр | Значение |
|----------|---------|
| Физика | Ethernet (прямой кабель или через switch) |
| Протокол | ROS2 (DDS — CycloneDDS или FastDDS) |
| Пропускная способность | 1 Gbps |
| Задержка | < 1 ms |
| Данные ↑ (Nano → NX) | Карта (OccupancyGrid), поза робота (Odometry), point cloud сжатый |
| Данные ↓ (NX → Nano) | Навигационные цели (PoseStamped), команды планировщика |

### Уровень 2 ↔ Уровень 3: Ethernet + ROS2 DDS

| Параметр | Значение |
|----------|---------|
| Физика | Ethernet |
| Протокол | ROS2 DDS |
| Данные ↑ (RPi → Nano) | Детекции (BoundingBox3DArray), tracked objects |
| Данные ↓ (Nano → RPi) | Поза для coordinate transform, параметры камеры |
| Данные ↑ (RPi → NX) | Распознанные лица, жесты, события |

### Уровень 2 ↔ Уровень 4: UART (rosserial)

| Параметр | Значение |
|----------|---------|
| Физика | USB (виртуальный COM) или прямой UART |
| Протокол | rosserial или micro-ROS (предпочтительнее) |
| Скорость | 115200–1000000 baud |
| Задержка | < 5 ms |
| Данные ↓ (Nano → Arduino) | Скорости моторов (Twist → ШИМ), углы серв |
| Данные ↑ (Arduino → Nano) | Энкодеры, состояние батареи, bumper events, E-stop |

### Уровень 1 ↔ Уровень 3: Ethernet + ROS2 DDS

| Параметр | Значение |
|----------|---------|
| Данные ↑ (RPi → NX) | Результаты детекции для фьюжна и LLM |
| Данные ↓ (NX → RPi) | Запросы на специфическую детекцию (ищи X) |

---

## ROS2 — Topic Map (предварительный)

### Навигация и SLAM

| Topic | Тип | Издатель | Подписчик |
|-------|-----|---------|-----------|
| `/scan` | `sensor_msgs/LaserScan` | Nano (RPLIDAR) | Nano (SLAM) |
| `/map` | `nav_msgs/OccupancyGrid` | Nano (SLAM) | NX, RPi |
| `/odom` | `nav_msgs/Odometry` | Nano (энкодеры+IMU) | NX, Nano |
| `/cmd_vel` | `geometry_msgs/Twist` | Nano (nav) | Arduino |
| `/goal_pose` | `geometry_msgs/PoseStamped` | NX (планировщик) | Nano |

### Компьютерное зрение

| Topic | Тип | Издатель | Подписчик |
|-------|-----|---------|-----------|
| `/camera/rgb/image` | `sensor_msgs/Image` | RPi (камера) | RPi (YOLO) |
| `/camera/depth/image` | `sensor_msgs/Image` | Nano (D435i) | Nano |
| `/camera/depth/points` | `sensor_msgs/PointCloud2` | Nano (D435i) | NX (фьюжн) |
| `/detections` | `vision_msgs/Detection2DArray` | RPi (YOLO) | NX, Nano |
| `/faces` | custom msg | RPi | NX |
| `/gestures` | custom msg | RPi | NX |

### Голос и диалог

| Topic | Тип | Издатель | Подписчик |
|-------|-----|---------|-----------|
| `/audio/input` | `audio_msgs/Audio` | NX (микрофон) | NX (Whisper) |
| `/speech/text` | `std_msgs/String` | NX (Whisper) | NX (LLM) |
| `/speech/output` | `audio_msgs/Audio` | NX (TTS) | NX (динамик) |
| `/llm/response` | `std_msgs/String` | NX (LLM) | NX (TTS), RPi |

### Управление

| Topic | Тип | Издатель | Подписчик |
|-------|-----|---------|-----------|
| `/motors/pwm` | custom msg | Nano | Arduino |
| `/servos/angles` | custom msg | Nano | Arduino |
| `/encoders` | custom msg | Arduino | Nano |
| `/battery` | `sensor_msgs/BatteryState` | Arduino | Все |
| `/emergency_stop` | `std_msgs/Bool` | Arduino | Все |

---

## Варианты физической сети

### Вариант A: Ethernet switch (рекомендуемый)

```
[Orin NX]──ETH──┐
                 ├──[Gigabit Switch 5-port]
[Nano]─────ETH──┤
                 │
[RPi 5]────ETH──┘
```

- Плюсы: стандарт, низкая задержка, надёжно
- Минусы: лишний кабель + switch, вес

### Вариант B: Wi-Fi mesh (для мониторинга)

- RPi 5 как Wi-Fi AP → ноутбук подключается для мониторинга/rviz2
- Основная связь между платами — только Ethernet

### Вариант C: USB между Nano и Arduino

- Nano → Arduino Mega через USB (serial)
- Самый простой вариант, micro-ROS поддерживает

---

## Middleware: ROS2 Humble / Jazzy

| Параметр | Выбор | Причина |
|----------|-------|---------|
| Дистрибутив | ROS2 Humble (LTS до 2027) или Jazzy | Стабильность + поддержка |
| DDS | CycloneDDS | Легковеснее FastDDS, лучше для embedded |
| Сериализация | CDR (стандарт DDS) | Автоматически с ROS2 |
| QoS | Reliable для команд, BestEffort для видео | Баланс надёжности и скорости |
