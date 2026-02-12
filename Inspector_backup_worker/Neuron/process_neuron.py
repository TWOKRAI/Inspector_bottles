import tensorflow as tf
import cv2
import numpy as np


class NeuralProcessor:
    def __init__(self, model_path):
        self.enable = True
        self.model = self._load_model(model_path)
        self.label = 'None'

        self.predicted_class = 1
        self.predict_value = 0.35

        self.find_object_train = False


    def _load_model_custom(self, model_path):
        try:
            # Загружаем модель с кастомными объектами
            model = tf.keras.models.load_model(
                model_path,
                custom_objects={
                    'prec': tf.keras.metrics.Precision(name='prec'),
                    'rec': tf.keras.metrics.Recall(name='rec')
                }
            )
            
            # Явная перекомпиляция для совместимости
            model.compile(
                optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
                loss='binary_crossentropy',
                metrics=['accuracy', 'prec', 'rec']
            )
            return model
        except Exception as e:
            print(f"Error loading model: {e}")
            return None

    def _load_model(self, model_path):
        try:
            # Загружаем модель с кастомными объектами
            model = tf.keras.models.load_model(model_path)

            return model
        except Exception as e:
            print(f"Error loading model: {e}")
            return None


    def neuroun_predict(self, input_list):
        if not self.model:
            print("Model is not loaded.")
            return None, None

        try:
            frame_id, img, img_cnn, x, y, r, timestamp = input_list
        except ValueError as e:
            print(f"Error unpacking input_list: {e}")
            return None, None

        label = 'None'
        color = (255, 255, 255)  # Белый (default)

        try:
            if self.model:
                #predict = self.model.predict(img_cnn, verbose=0)
                img_normalized = img / 255.0
                input_tensor = np.expand_dims(img_normalized, axis=0)

                debug_img = (img_normalized * 255).astype(np.uint8)
                cv2.imwrite('debug_processed.jpg', debug_img)
                
                prediction = self.model.predict(input_tensor, verbose=1)

                self.predicted_class = prediction[0][0]
                print('self.predicted_class', self.predicted_class)
        except Exception as e:
            print(f"Error during prediction: {e}")
            return None, None
        

        if self.predicted_class >= 0.45:
            label = "Good"
            color = (0, 255, 0)  # Зеленый
        else:
            label = "Bad"
            color = (0, 0, 255)  # Красный


        result = (label, x, y, r, timestamp, frame_id)
        output = (frame_id, img, img_cnn, x, y, r, label, color)

        return result, output


    def clear_session(self):
        tf.keras.backend.clear_session()
        pass


    def neuroun_predict_batches(self, input_batch):
        """Обрабатывает батч изображений за один вызов модели"""
        if not self.model:
            print("Model is not loaded.")
            return []

        try:
            # Собираем данные для батча
            batch_images = []
            #batch_metadata = []
            
            # Подготавливаем данные
            for img in input_batch:
                try:
                    #frame_id, img, x, y, r, timestamp = input_item

                    # frame_id = input_item['frame_id']
                    #img = input_item['img']
                    # x = input_item['x'] 
                    # y = input_item['y'] 
                    # r  = input_item['r'] 
                    # timestamp = input_item['timestamp'] 

                    #   print("Тип данных изображения:", img.dtype)  # Должно быть np.uint8 или np.uint32
                    #print("Размерность изображения:", img.shape) # Формат (height, width, channels)

                    # Конвертация BGR → RGB и изменение размера
                    #img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    img = cv2.resize(img, (72, 72))

                    # Нормализация и добавление в батч
                    #img_normalized = img.astype(np.float32) / 255.0


                    # Нормализация и добавление размерности батча
                    img_normalized = img.astype(np.uint8) / 255.0

                    batch_images.append(img_normalized)
                    # batch_metadata.append({
                    #     'frame_id': frame_id,
                    #     'img': img,
                    #     'x': x,
                    #     'y': y,
                    #     'r': r,
                    #     'timestamp': timestamp
                    # })
                except Exception as e:
                    print(f"Error processing input item: {e}")
                    return []

            if not batch_images:
                #print("Empty batch")
                return []

            # Преобразуем в тензор (batch_size, height, width, channels)
            input_tensor = np.array(batch_images)

            # Выполняем предсказание для всего батча
            predictions = self.model.predict(input_tensor, verbose=0)
            
            return predictions

        except Exception as e:
            # print(' (results, outputs)',  results, outputs)
            print(f"Error during batch prediction: {e}")
            return []