import os
import cv2
import numpy as np
import shutil
import tensorflow as tf

def sort_images(input_dir, output_dir1, output_dir2, model, batch_size=32, target_size=(72, 72), threshold=0.5):
    """
    Сортирует изображения с использованием OpenCV для загрузки и обрабатывает их батчами.
    """
    # Создаем выходные директории
    os.makedirs(output_dir1, exist_ok=True)
    os.makedirs(output_dir2, exist_ok=True)

    # Поддерживаемые форматы
    valid_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

    # Получаем общее количество изображений
    all_images = len([f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions)])


    # Список для хранения изображений и метаданных
    batch_images = []
    batch_filenames = []

    i = 0

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
                batch_filenames.append(file_path)

                # Если батч полон, выполняем предсказание
                if len(batch_images) == batch_size:
                    predictions = model.predict(np.array(batch_images), verbose=0)
                    process_batch(predictions, batch_filenames, output_dir1, output_dir2, threshold)
                    batch_images = []
                    batch_filenames = []

                    # Выводим прогресс
                    print(f'{i + 1} / {(all_images + batch_size - 1) // batch_size}')
                    i += 1 
                
                if i > 50:
                    break

            except Exception as e:
                print(f"Ошибка в файле {filename}: {str(e)}")

    # Обработка оставшихся изображений, если батч не полон
    if batch_images:
        predictions = model.predict(np.array(batch_images), verbose=0)
        process_batch(predictions, batch_filenames, output_dir1, output_dir2, threshold)

def process_batch(predictions, filenames, output_dir1, output_dir2, threshold):
    """
    Обрабатывает результаты предсказаний и копирует файлы в соответствующие директории.
    """
    for prediction, filename in zip(predictions, filenames):
        dest_dir = output_dir1 if prediction[0] > threshold else output_dir2
        #shutil.copy(filename, os.path.join(dest_dir, os.path.basename(filename)))


import time


class Timer:
    def __init__(self, name):
        self.name = name
        self.start_time = None


    def start(self):
        """Начинает отсчет времени и сохраняет текущее время в атрибут start_time."""
        self.start_time = time.time()
        #print(f"Таймер {self.name} запущен")


    def elapsed_time(self):
        """Возвращает количество секунд, прошедших с момента запуска таймера."""
        if self.start_time is None:
            #print(f"Таймер {self.name} не был запущен.")
            return 0
        else:
            elapsed = (time.time() - self.start_time)
            print(f"Таймер {self.name} {elapsed}")
            return elapsed
        
my_timer = Timer('1')

my_timer.start()

# Загрузка модели
model = tf.keras.models.load_model("Neuron/Models/waffle_classifier_v21.keras")

# Вызов функции сортировки
sort_images(
    input_dir=r'C:\dev\Data image\Sorting Neuroun\Image_Save',
    output_dir1=r'C:\dev\Data image\Sorting Neuroun\Good',
    output_dir2=r'C:\dev\Data image\Sorting Neuroun\Bad',
    model=model,
    batch_size=32,
    target_size=(72, 72),
    threshold=0.2
)

my_timer.elapsed_time()