import threading
from queue import Empty
import numpy as np
import time

from Neuron.process_neuron import NeuralProcessor
from Neuron.find_color_area import is_color_area_above_threshold
from Utils.timer import Timer


class NeuralProcessingManager:
    def __init__(self, queue_manager, name, model_path):
        self.name_process = str(name)
        self.queue_manager = queue_manager

        self.stop_proccess = False

        #self.result_queue = queue_manager.result_queue
        self.neural_input_queue = queue_manager.input_draw_queue
        self.neural_output_queue = queue_manager.neural_output_queue

        self.model_path = model_path
        self.neural_processor = NeuralProcessor(self.model_path)

        self.control_neuroun = {}
        self.init_control()

        self.control_thread = threading.Thread(target=self.control_update_thread)
        self.main_thread = threading.Thread(target=self.neural_processing_thread)
        
        # for _ in range(10):
        #     batch_images = [
        #         np.random.randint(0, 256, (72, 72, 3), dtype=np.uint8) for _ in range(7)
        #     ]

        #     self.neural_processor.neuroun_predict_batches(batch_images)


        print(f'Процесс нейрон {self.name_process} запущен')
        queue_manager.download.put((self.name_process, True))


    def start(self):
        self.main_thread.start()
        self.control_thread.start()

    
    def stop(self):
        self.stop_proccess = True

        self.main_thread.join()
        self.control_thread.join()

        print(f'Процесс нейрон {self.name_process} остановлен')


    def get_control(self):
        self.neural_processor.predict_value = self.control_neuroun.get('predict', 0.5)
        self.neuroun = self.control_neuroun.get('neuroun', False)
        self.find_object = self.control_neuroun.get('find_object', True)
        self.find_object_train = self.control_neuroun.get('find_object_train', False)
        
        #print('predict', self.neural_processor.predict_value, self.neuroun)


    def control_update_thread(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            # try:
            #     #self.control_neuroun = self.queue_manager.control_neuroun.get(timeout=1)
            #     self.control_neuroun = self.queue_manager.control_neuroun.get_nowait()
            # except Empty:
            #     time.sleep(0.1)
            #     continue

            #self.queue_manager.control_neuroun_event.wait()
            self.control_neuroun = self.queue_manager.control_neuroun.get()
            #self.queue_manager.control_neuroun_event.clear()

            self.get_control()


    def init_control(self):
        try:
            self.control_neuroun = self.queue_manager.control_neuroun.get(timeout=1)
        except Empty:
            pass
        
        self.get_control()


    def neural_processing_thread(self):
        total_all = 0
        total_bad = 0
        total_good = 0

        target_color = {
            'lower': [103, 157, 0],  # Нижняя граница березового цвета в HSV
            'upper': [180, 255, 255] # Верхняя граница березового цвета в HSV
        }

        timer = Timer('Neuroun')
        
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            #input_list = []

            #self.queue_manager.neuroun_event.wait(timeout=0.1)
            # try:
            #     #print('нейрон слушаем')
            #     #data_frame = self.queue_manager.neuroun_queue.get(timeout=0.1)
            #     data_frame = self.queue_manager.neuroun_queue.get_nowait()
            #     #print('я получил данные для нейрона')
            # except Empty:
            #     time.sleep(0.01)
            #     #print('нет дата данных для нейрона')
            #     continue

            # try:
            #     data_frame = self.queue_manager.neuroun_queue.get_nowait()
            # except Empty:
            #     time.sleep(0.01)
            #     continue
            
            data_frame = self.queue_manager.neuroun_queue.get()

            if data_frame == 'clear_session':
                self.neural_processor.clear_session()
                continue
            

            #self.queue_manager.neuroun_event.clear()

            #timestamp = data_frame['current_time']

            #print((time.time() - timestamp) * 1000)

            
            timer.start()

            # if input_list == 'clear':
            #     self.neural_processor.clear_session()
            #     self.neural_output_queue.put(1)
            #     continue
            
            # outputs = []
            # results = []
            predictions = []
            batch_robot = []

            if self.neuroun:
                id_memory = data_frame['id_memory']
                batch_metadata = data_frame['batch_metadata']

                #print(len(batch_metadata))

                #print(data_frame['batch_metadata'])
                #print("считываю из нейронки памяти")

                batch_images = self.queue_manager.memory_manager.read_images("neuroun_data", id_memory, len(batch_metadata))
                #print('neuroun batch_images', len(batch_images), len(batch_metadata), 'id', id_memory)

                # if self.find_object:
                #     if len(batch_images) > 0:
                        
                #         #continue
                #     # results, outputs = self.neural_processor.neuroun_predict_batches(input_list)
                    
                #         predictions = self.neural_processor.neuroun_predict_batches(batch_images)
                #     else:
                #         #print('нет изображения с батчами')
                #         pass
  
                #     if len(predictions) > 0:       
                #         for i, pred in enumerate(predictions):
                #             # meta = input_list[i]
                #             predicted_value = pred[0]

                #             batch_metadata[i]['predict_value'] = predicted_value

                #             # Определяем метку и цвет
                #             if predicted_value >= self.neural_processor.predict_value:
                #                 batch_metadata[i]['category'] = "Good"
                #                 #color = (0, 255, 0)
                #                 total_good += 1
                #             else:
                #                 batch_metadata[i]['category'] = "Bad"
                #                 #color = (0, 0, 255)
                #                 total_bad += 1
                                
                #                 batch_robot.append(batch_metadata[i])

                # if self.find_object_train:
                #     for i, img in enumerate(batch_images):
                #         if is_color_area_above_threshold(img, target_color, 30):
                #             batch_metadata[i]['category'] = 'Bad'
                #             batch_metadata[i]['predict_value'] = 0

                #             batch_robot.append(batch_metadata[i])
                #         else:
                #             if not self.find_object:
                #                 batch_metadata[i]['category'] = "Train"
                #                 batch_metadata[i]['predict_value'] = 1

                if self.find_object or self.find_object_train:
                    batch_images = self.queue_manager.memory_manager.read_images("neuroun_data", id_memory, len(batch_metadata))

                    if self.find_object:
                        if len(batch_images) > 0:        
                            predictions = self.neural_processor.neuroun_predict_batches(batch_images)
                        else:
                            #print('нет изображения с батчами')
                            pass

                    for i, img in enumerate(batch_metadata):
                        if self.find_object:
                            if i < len(predictions):     
                                predicted_value  = predictions[i][0]
                                batch_metadata[i]['predict_value'] = predicted_value 

                                if predicted_value >= self.neural_processor.predict_value:
                                    batch_metadata[i]['category'] = "Good"
                                    #color = (0, 255, 0)
                                    total_good += 1
                                else:
                                    batch_metadata[i]['category'] = "Bad"
                                    #color = (0, 0, 255)
                                    total_bad += 1
                                    
                                    batch_robot.append(batch_metadata[i])
                                    continue
                            else:
                                batch_metadata[i]['predict_value'] = predicted_value 
                                batch_metadata[i]['category'] = "Good"

                        if self.find_object_train:
                            img = batch_images[i]

                            if is_color_area_above_threshold(img, target_color, 30):
                                batch_metadata[i]['category'] = 'Bad'
                                batch_metadata[i]['predict_value'] = 0

                                batch_robot.append(batch_metadata[i])
                            else:
                                if not self.find_object:
                                    batch_metadata[i]['category'] = "Train"
                                    batch_metadata[i]['predict_value'] = 1

                            # for i, pred in enumerate(predictions):
                            #     predicted_value = pred[0]

                            #     batch_metadata[i]['predict_value'] = predicted_value
                                
                            #     # Определяем метку и цвет
                            #     if predicted_value >= self.neural_processor.predict_value:
                            #         batch_metadata[i]['category'] = "Good"
                            #         #color = (0, 255, 0)
                            #         total_good += 1
                            #     else:
                            #         batch_metadata[i]['category'] = "Bad"
                            #         #color = (0, 0, 255)
                            #         total_bad += 1
                                    
                            #         batch_robot.append(batch_metadata[i])

                    # if len(batch_metadata) == 0:
                    #     self.neural_processor.clear_session()
                    # if self.find_object_train:
                    #     img = batch_images[i]

                    #     if is_color_area_above_threshold(img, target_color, 30):
                    #         batch_metadata[i]['category'] = 'Bad'
                    #         batch_metadata[i]['predict_value'] = 0

                    #         batch_robot.append(batch_metadata[i])
                    #     else:
                    #         if not self.find_object:
                    #             batch_metadata[i]['category'] = "Train"
                    #             batch_metadata[i]['predict_value'] = 1
                
                data_frame['total_good'] = total_good
                data_frame['total_bad'] = total_bad

                data_frame['batch_metadata'] = batch_metadata

            timer.elapsed_time(print_log=False)
            #print('batch_size', len(batch_images))

            if len(batch_robot) > 0 and self.queue_manager.robot_on.is_set():
            #if self.queue_manager.robot_on.is_set():
            #if len(batch_robot) > 0:
                self.queue_manager.remove_old_frame_if_full(self.queue_manager.robot_queue)
                self.queue_manager.robot_queue.put(batch_robot)
                self.queue_manager.robot_event.set()
            
            
            #print('time neuroun', timer.elapsed_time())
            #print('neuroun ready', time.time() - data_frame['current_time'])

            #print("Отправляю результат нейронки на рисование")

            self.queue_manager.remove_old_frame_if_full(self.queue_manager.draw_queue)
            self.queue_manager.draw_queue.put(data_frame)
            self.queue_manager.draw_event.set()


            #print(f'Всего - {total_good + total_bad}  Хороших - {total_good}  Плохих - {total_bad}')
        
        self.neural_processor.clear_session()
        print("процесс нейрон остановился")

def neural_processing(queue_manager, name):
    neuroun = NeuralProcessingManager(
        queue_manager, 
        name = name, 
        model_path = "Neuron/Models/waffle_classifier_v203.keras",  
    )
    
    neuroun.start()
