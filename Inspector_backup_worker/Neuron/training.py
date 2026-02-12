import os
import cv2
import numpy as np
import time
from tensorflow.keras import layers, models, callbacks, utils
import tensorflow as tf

# Конфигурация
IMG_SIZE = 72
BATCH_SIZE = 64
EPOCHS = 100
DATA_PATH = 'train_images'
CLASSES = {'bad': 0, 'good': 1}

# 1. Загрузка данных с HSV-конвертацией
class HSVDataLoader:
    def __init__(self):
        self.cache = {}
        
    def load_image(self, path):
        if path in self.cache:
            return self.cache[path]
            
        img = cv2.imread(path)
        img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV_FULL)  # Полный диапазон HUE
        img = img.astype('float32')
        img[..., 0] /= 255.0  # H [0-255] → [0-1]
        img[..., 1] /= 255.0  # S [0-255] → [0-1]
        img[..., 2] /= 255.0  # V [0-255] → [0-1]
        self.cache[path] = img
        return img

    def load_dataset(self):
        images = []
        labels = []
        
        for class_name, label in CLASSES.items():
            class_dir = os.path.join(DATA_PATH, class_name)
            for filename in os.listdir(class_dir):
                img_path = os.path.join(class_dir, filename)
                img = self.load_image(img_path)
                images.append(img)
                labels.append(label)
                
        return np.array(images), np.array(labels)

# 2. Глубокая модель с HSV-оптимизацией
def create_hsv_model():
    model = models.Sequential([
        layers.Conv2D(32, (5,5), activation='relu', input_shape=(IMG_SIZE, IMG_SIZE, 3)),
        layers.BatchNormalization(),
        layers.MaxPooling2D(2),
        
        layers.SeparableConv2D(64, (3,3), activation='relu'),
        layers.SeparableConv2D(64, (3,3), activation='relu'),
        layers.MaxPooling2D(2),
        
        layers.SeparableConv2D(128, (3,3), activation='relu'),
        layers.GlobalAveragePooling2D(),
        
        layers.Dense(128, activation='relu', kernel_regularizer='l2'),
        layers.Dropout(0.3),
        layers.Dense(1, activation='sigmoid')
    ])
    
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss='binary_crossentropy',
        metrics=[
            'accuracy',
            tf.keras.metrics.Precision(name='precision'),
            tf.keras.metrics.Recall(name='recall')
        ]
    )
    return model

# 3. Обучение с аугментацией HSV
def train_model():
    dataloader = HSVDataLoader()
    X, y = dataloader.load_dataset()
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, stratify=y)
    
    # Аугментация для HSV
    datagen = utils.image.ImageDataGenerator(
        rotation_range=20,
        width_shift_range=0.15,
        height_shift_range=0.15,
        shear_range=0.1,
        zoom_range=0.1,
        brightness_range=[0.8,1.2],
        channel_shift_range=0.1
    )
    
    model = create_hsv_model()
    
    callbacks = [
        callbacks.EarlyStopping(patience=15, restore_best_weights=True),
        callbacks.ModelCheckpoint('best_hsv_model.keras', save_best_only=True),
        callbacks.ReduceLROnPlateau(factor=0.5, patience=5)
    ]
    
    history = model.fit(
        datagen.flow(X_train, y_train, batch_size=BATCH_SIZE),
        steps_per_epoch=len(X_train) // BATCH_SIZE,
        epochs=EPOCHS,
        validation_data=(X_val, y_val),
        callbacks=callbacks,
        verbose=2
    )
    
    return model

# 4. Оптимизированный предиктор
class HSVWaffleClassifier:
    def __init__(self, model_path='best_hsv_model.keras'):
        self.model = models.load_model(model_path)
        self.model._make_predict_function()  # Для ускорения CPU
        
    def predict(self, image_path):
        # Препроцессинг
        start_time = time.time()
        img = cv2.imread(image_path)
        img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        img = img.astype('float32')
        img[..., 0] /= 179.0
        img[..., 1] /= 255.0
        img[..., 2] /= 255.0
        img = np.expand_dims(img, axis=0)
        
        # Предсказание
        prediction = self.model.predict(img, verbose=0)[0][0]
        
        return {
            'class': 'good' if prediction > 0.5 else 'bad',
            'confidence': float(prediction),
            'time_ms': round((time.time()-start_time)*1000, 1)
        }

# Запуск
if __name__ == "__main__":
    # Обучение (на GPU)
    model = train_model()
    
    # Тестирование
    classifier = HSVWaffleClassifier()
    result = classifier.predict('test_image.jpg')
    print(f"Результат: {result}")
