import tensorflow as tf
import cv2
import numpy as np
import matplotlib.pyplot as plt


class NeuralBase:
    """Базовый класс с общими методами"""
    def __init__(self):
        self.label = 'None'
        self.find_object_train = False

    def preprocess_image(self, img):
        """Общая предобработка изображения"""
        #img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        #cv2.imwrite('test.jpg', img) 
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (72, 72))
        
        # plt.imshow(img)
        # plt.show()
        # input()
        return img
    
    def round_matrix(self, matrix, decimals=2):
        """
        Округляет все значения в двумерном списке до заданного количества знаков после запятой.

        :param matrix: Двумерный список (матрица) с числами.
        :param decimals: Количество знаков после запятой для округления.
        :return: Новый двумерный список с округленными значениями.
        """
        return [[round(value, decimals) for value in row] for row in matrix]


    def clear_session(self):
        """Очистка ресурсов (переопределить в дочерних классах)"""
        pass

class KerasProcessor(NeuralBase):
    """Обработчик для Keras моделей"""
    def __init__(self, model_path):
        super().__init__()
        self.model = self._load_model(model_path)

    def _load_model(self, model_path):
        """Загрузка Keras модели"""
        try:
            model = tf.keras.models.load_model(
                model_path,
                custom_objects={
                    'prec': tf.keras.metrics.Precision(name='prec'),
                    'rec': tf.keras.metrics.Recall(name='rec')
                }
            )
            print(f"Keras model loaded. Input shape: {model.input_shape}")
            return model
        except Exception as e:
            print(f"Error loading Keras model: {e}")
            return None

    def get_num_classes(self):
        if self.model:
            return self.model.output_shape[-1]
        return 0

    def predict_single(self, img):
        """Предсказание для одного изображения"""
        if not self.model:
            return None
            
        processed_img = self.preprocess_image(img)
        input_tensor = np.expand_dims(processed_img.astype(np.float32)/255, axis=0)
        prediction = self.model.predict(input_tensor, verbose=0)
        return prediction.squeeze()

    def predict_batch(self, batch):
        """Обработка батча"""
        processed_batch = [self.preprocess_image(img).astype(np.float32)/255 for img in batch]
        predict_list = self.model.predict(np.array(processed_batch), verbose=0)
        
        return self.round_matrix(predict_list)

    def clear_session(self):
        """Очистка сессии Keras"""
        tf.keras.backend.clear_session()
        #self.model = None

class TFLiteProcessor(NeuralBase):
    """Обработчик для TFLite моделей"""
    def __init__(self, model_path):
        super().__init__()
        self.interpreter = self._load_model(model_path)
        self._prepare_model()

    def _load_model(self, model_path):
        """Загрузка TFLite модели"""
        try:
            interpreter = tf.lite.Interpreter(model_path=model_path)
            print("TFLite model loaded successfully")
            return interpreter
        except Exception as e:
            print(f"Error loading TFLite model: {e}")
            return None

    def _prepare_model(self):
        """Подготовка модели к работе"""
        if self.interpreter:
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()
            self.output_details = self.interpreter.get_output_details()
            print(f"Input details: {self.input_details[0]}")

    def get_num_classes(self):
        if self.output_details:
            return self.output_details[0]['shape'][-1]
        return 0

    def predict_single(self, img):
        """Предсказание для одного изображения"""
        if not self.interpreter:
            return None
            
        processed_img = self.preprocess_image(img)
        input_tensor = self._convert_input(processed_img)
        input_tensor = np.expand_dims(input_tensor, axis=0)
        
        self.interpreter.set_tensor(self.input_details[0]['index'], input_tensor)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]['index'])
        return output.squeeze()
        

    def predict_batch(self, batch):
        try:
            # Обработка и проверка изображений
            processed = []
            for img in batch:
                img = self.preprocess_image(img)
                if len(img.shape) != 3 or img.shape[2] != 3:
                    raise ValueError("Invalid image shape after preprocessing")
                processed.append(self._convert_input(img))
            
            input_tensor = np.array(processed)
            
            # Проверка совпадения размерностей
            expected_shape = self.input_details[0]['shape'][1:]
            if input_tensor.shape[1:] != tuple(expected_shape):
                raise ValueError(
                    f"Input shape mismatch. Expected {expected_shape}, " 
                    f"got {input_tensor.shape[1:]}")
            
            # Настройка батча
            self._adjust_batch_size(input_tensor.shape[0])
            
            # Установка данных
            self.interpreter.set_tensor(
                self.input_details[0]['index'], input_tensor)
            self.interpreter.invoke()

            predict_list = self.interpreter.get_tensor(self.output_details[0]['index'])
            self.round_matrix(predict_list)
            return self.round_matrix(predict_list)
        except Exception as e:
            print(f"Batch error: {str(e)}")
            return []

    def _convert_input(self, img):
        target_type = self.input_details[0]['dtype']

        if target_type == np.uint8:
            return img.astype(np.uint8)
        return (img.astype(np.float32) / 255.0)

    def _adjust_batch_size(self, batch_size):
        current_shape = self.input_details[0]['shape'].copy()
        if current_shape[0] != batch_size:
            current_shape[0] = batch_size
            self.interpreter.resize_tensor_input(
                self.input_details[0]['index'], current_shape)
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()

    def clear_session(self):
        """Очистка ресурсов TFLite"""
        # self.interpreter = None
        # self.input_details = None
        # self.output_details = None
        pass


class NeuralProcessor:
    """Универсальный обработчик моделей"""
    def __init__(self, model_path, thresholds=None, class_labels=None, class_colors=None):
        self.processor = self._create_processor(model_path)
        raw_num_classes = self.processor.get_num_classes()
        self.is_binary = raw_num_classes == 1
        self.num_classes = 2 if self.is_binary else raw_num_classes

        # Инициализация меток классов
        if class_labels is None:
            if self.is_binary:
                self.class_labels = ["Bad", "Good"]
            else:
                self.class_labels = [f'Class_{i}' for i in range(self.num_classes)]
        else:
            required_labels = 2 if self.is_binary else self.num_classes
            if len(class_labels) != required_labels:
                raise ValueError(f"Expected {required_labels} class labels, got {len(class_labels)}")
            self.class_labels = class_labels

        # Инициализация порогов
        if thresholds is None:
            self.thresholds = [0.5] if self.is_binary else [0.5] * self.num_classes
        else:
            required_thresholds = 1 if self.is_binary else self.num_classes
            if len(thresholds) != required_thresholds:
                raise ValueError(f"Expected {required_thresholds} thresholds, got {len(thresholds)}")
            self.thresholds = thresholds

        # Инициализация цветов
        if class_colors is None:
            if self.is_binary:
                self.class_colors = [(0, 0, 255), (0, 255, 0)]
            else:
                self.class_colors = [(0, 255, 0) if i == 0 else (0, 0, 255) for i in range(self.num_classes)]
        else:
            required_colors = 2 if self.is_binary else self.num_classes
            if len(class_colors) != required_colors:
                raise ValueError(f"Expected {required_colors} colors, got {len(class_colors)}")
            self.class_colors = class_colors

    def _create_processor(self, model_path):
        """Создает соответствующий обработчик"""
        if model_path.endswith(('.keras', '.h5')):
            return KerasProcessor(model_path)
        elif model_path.endswith('.tflite'):
            return TFLiteProcessor(model_path)
        raise ValueError("Unsupported model format")

    def neuroun_predict(self, image):
        """Интерфейсный метод для предсказания"""
        predictions = self.processor.predict_single(image)
        return predictions 


    def neuroun_predict_batches(self, input_batch):
        """Интерфейсный метод для батчевой обработки"""
        images = []

        for item in input_batch:
            try:
                img = item
                images.append(img)
            except (IndexError, TypeError) as e:
                print(f"Error extracting image from batch item: {e}")
                continue
        if not images:
            return []
        return self.processor.predict_batch(images)

    def classify_with_thresholds_and_max(self, probabilities, thresholds):
        # Проверка по порогам с приоритетом классов: 0 -> 1 -> 2
        if probabilities[0] >= thresholds[0]:
            return 0, probabilities[0]
        elif probabilities[1] >= thresholds[1]:
            return 1, probabilities[1]
        elif probabilities[2] >= thresholds[2]:
            return 2, probabilities[2]
        else:
            # Если ни один порог не превышен - возвращаем индекс максимума
            max_index = np.argmax(probabilities)
            return max_index, probabilities[max_index]
        
    def clear_session(self):
        """Очистка ресурсов"""
        self.processor.clear_session()