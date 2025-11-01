# Clean Camera App

Минимальное приложение для работы с камерами Hikvision/MindVision без лишних зависимостей.

## Описание

Это приложение предоставляет чистый интерфейс для:
- Поиска и подключения к камерам (GigE и USB)
- Захвата изображений в реальном времени
- Управления параметрами камеры (Frame Rate, Exposure Time, Gain)
- Отображения FPS в реальном времени

## Требования

- Python 3.7+
- Windows (требуется MvCameraControl.dll)
- Камера Hikvision/MindVision

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Убедитесь, что файл `MvCameraControl.dll` находится в системном PATH или в папке с приложением.

## Запуск

```bash
python clean_camera_test.py
```

## Использование

1. **Enum Devices** - Поиск доступных камер
2. **Open** - Подключение к выбранной камере
3. **Start Grabbing** - Начало захвата кадров
4. **Get Parameters** - Получение текущих параметров камеры
5. **Set Parameters** - Установка новых параметров
6. **Stop Grabbing** - Остановка захвата
7. **Close** - Отключение от камеры

## Структура файлов

```
clean_camera_app/
├── clean_camera_test.py          # Основное приложение
├── camera_process/
│   └── clean_camera_process.py  # Менеджер процессов камеры
├── MvCameraControl_class.py     # SDK классы камеры
├── MvErrorDefine_const.py       # Коды ошибок
├── CameraParams_header.py        # Параметры камеры
├── CameraParams_const.py         # Константы камеры
├── PixelType_header.py          # Типы пикселей
├── requirements.txt             # Зависимости Python
└── README.md                    # Этот файл
```

## Особенности

- **Без обработки изображений** - показывает RAW данные с камеры
- **Многопроцессность** - камера работает в отдельном процессе
- **Простая демозаика** - автоматическая обработка Bayer pattern
- **Реальное время** - отображение FPS и параметров камеры

## Поддерживаемые форматы

- Mono8, Mono16
- Bayer RG8, RG10, RG12
- RGB8, RGB10, RGB12
- YUV422, YUV444

## Устранение неполадок

1. **"No devices found"** - Проверьте подключение камеры и драйверы
2. **"Failed to open camera"** - Убедитесь, что камера не используется другим приложением
3. **"DLL not found"** - Установите MvCameraControl.dll в системный PATH

## Лицензия

Этот код предназначен для использования с камерами Hikvision/MindVision.
