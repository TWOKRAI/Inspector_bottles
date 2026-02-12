import os
import time
import cv2
import numpy as np

from process_neuron import NeuralProcessor



def benchmark(folder_path, target_size=(72, 72), batch_sizes=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]):
    """
    Тестирует производительность модели на изображениях из указанной папки
    :param model: Загруженная модель Keras
    :param folder_path: Путь к папке с изображениями
    :param target_size: Размер для ресайза изображений (ширина, высота)
    :param batch_sizes: Список размеров батчей для тестирования
    """

    model_path = "Neuron\Models\waffle_classifier_v1.keras" 
    neural_processor = NeuralProcessor(model_path)

    # Загрузка и предобработка изображений
    image_paths = [os.path.join(folder_path, f) 
                 for f in os.listdir(folder_path) 
                 if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    
    if not image_paths:
        print("Нет изображений для тестирования")
        return

    images = []
    for img_path in image_paths:
        try:
            # Загрузка и предобработка
            img = cv2.imread(img_path)
            if img is None:
                continue
                
            img = cv2.resize(img, target_size)  # Ресайз
            img = img.astype(np.float32) / 255.0  # Нормализация [0,1]
            images.append(img)
        except Exception as e:
            print(f"Ошибка обработки {img_path}: {e}")
    
    if not images:
        print("Не удалось загрузить изображения")
        return

    # Конвертация в numpy array
    images_array = np.array(images)
    print(f"Загружено изображений: {len(images_array)}")

    # Тестирование для каждого размера батча
    for bs in batch_sizes:
        try:
            total_time = 0
            num_batches = int(np.ceil(len(images_array) / bs))
            
            for i in range(num_batches):
                batch = images_array[i*bs : (i+1)*bs]
                
                start_time = time.time()
                #model.predict(batch, verbose=0)
                prediction = neural_processor.model.predict(batch, verbose=0)
                batch_time = time.time() - start_time
                
                total_time += batch_time
            
            avg_time_per_image = total_time / len(images_array)
            print(f"Batch {bs:2d} | "
                  f"Total: {total_time:.3f}s | "
                  f"Avg: {avg_time_per_image:.4f}s/img | "
                  f"Batches: {num_batches}")
        except Exception as e:
            print(f"Ошибка для batch_size={bs}: {e}")


benchmark('Neuron\Data_image\Data_all')