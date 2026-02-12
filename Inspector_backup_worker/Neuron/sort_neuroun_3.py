import os
import cv2
import numpy as np
import shutil
import tensorflow as tf

def sort_images(input_dir_good, input_dir_bad, output_dir_correct, output_dir_incorrect, model, batch_size=32, target_size=(72, 72), threshold=0.5):
    """
    Сортирует изображения с использованием OpenCV для загрузки и обрабатывает их батчами.
    """
    # Создаем выходные директории
    os.makedirs(output_dir_correct, exist_ok=True)
    os.makedirs(output_dir_incorrect, exist_ok=True)

    # Поддерживаемые форматы
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

    # Список для хранения изображений и метаданных
    batch_images = []
    batch_filenames = []

    i = 0

    def process_directory(input_dir, source_label):
        nonlocal i, batch_images, batch_filenames
        all_images = len([f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)])

        for filename in os.listdir(input_dir):
            if filename.lower().endswith(valid_extensions):
                file_path = os.path.join(input_dir, filename)

                try:
                    # Загрузка через OpenCV
                    img = cv2.imread(file_path)

                    if img is None:
                        raise ValueError("Не удалось загрузить изображение")

                    # Конвертация BGR -> RGB и изменение размера
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    img = cv2.resize(img, target_size)

                    # Нормализация и добавление в батч
                    img_normalized = img.astype(np.float32) / 255.0

                    batch_images.append(img_normalized)
                    batch_filenames.append((file_path, source_label))

                    # Если батч полон, выполняем предсказание
                    if len(batch_images) == batch_size:
                        predictions = model.predict(np.array(batch_images), verbose=0)
                        process_batch(predictions, batch_filenames, output_dir_correct, output_dir_incorrect, threshold)
                        batch_images = []
                        batch_filenames = []

                        # Выводим прогресс
                        print(f'{i + 1} / {(all_images + batch_size - 1) // batch_size}')
                        i += 1

                except Exception as e:
                    print(f"Ошибка в файле {filename}: {str(e)}")

        # Обработка оставшихся изображений, если батч не полон
        if batch_images:
            predictions = model.predict(np.array(batch_images), verbose=0)
            process_batch(predictions, batch_filenames, output_dir_correct, output_dir_incorrect, threshold)

    # Обработка обеих входных директорий
    process_directory(input_dir_good, "good")
    process_directory(input_dir_bad, "bad")

def process_batch(predictions, filenames, output_dir_correct, output_dir_incorrect, threshold):
    """
    Обрабатывает результаты предсказаний и копирует файлы в соответствующие директории.
    """
    for j, (prediction, (filename, source_label)) in enumerate(zip(predictions, filenames)):
        if (source_label == "good" and prediction[0] > threshold) or (source_label == "bad" and prediction[0] <= threshold):
            dest_dir = output_dir_correct
        else:
            dest_dir = output_dir_incorrect

        # Формируем новое имя файла
        base_name = os.path.basename(filename)
        new_filename = f"{source_label}_{os.path.basename(dest_dir)}_{j}_{base_name}"
        shutil.copy(filename, os.path.join(dest_dir, new_filename))

# Загрузка модели
model = tf.keras.models.load_model("Neuron/Models/waffle_classifier_v201.keras")

# Вызов функции сортировки
sort_images(
    input_dir_good = r'C:\dev\DataImage\good',
    input_dir_bad = r'C:\dev\DataImage\bad',
    output_dir_correct = r'C:\dev\DataImage\correct',
    output_dir_incorrect = r'C:\dev\DataImage\incorrect',
    model=model,
    batch_size=32,
    target_size=(72, 72),
    threshold=0.5
)
