"""Универсальный каталог плагинов — по доменам.

Каждый домен = подпапка с плагинами (plugin.py + config.py).
Каталог переносим — готов к переезду в multiprocess_framework/plugins/.

Домены:
- cameras/          Источники видео (webcam, simulator, hikvision, file)
- image_processing/ Обработка изображений (color_mask, blur, threshold)
- ml/               Нейросети (YOLO, ONNX, классификаторы)
- rendering/        Визуализация (overlay, display, stream)
- database/         Хранение данных (sqlite, postgres)
- hardware/         Железо (robot, PLC, сенсоры)
- services/         Инфраструктура (processor worker, health check)
"""
