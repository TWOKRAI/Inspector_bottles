import cv2
import time
import numpy as np
from queue import Empty

from Process_image.frame_detection import FrameDetection
from Neuron.find_color_area import is_color_area_above_threshold
from Utils.timer import Timer


def calculate_delay(fps):
    if fps <= 0:
        raise ValueError("FPS должно быть положительным числом")
    delay = 1000 / fps
    
    return delay


def process_frames(queue_manager, name):
    name_process = str(name)

    frame_detection = FrameDetection()

    inizialization = False

    frame_id = 0

    total_all = 0

    coll_clear = 0
    coll_null_total = 0

    print('Процесс обработки запущен')

    queue_manager.download.put((name_process, True))

    old_frame_x_1 = []

    controls = {}

    target_color = {
        'lower': [103, 157, 0],  # Нижняя граница березового цвета в HSV
        'upper': [180, 255, 255] # Верхняя граница березового цвета в HSV
    }


    interpolation_methods = {
        0: cv2.INTER_NEAREST,
        1: cv2.INTER_LINEAR,
        2: cv2.INTER_AREA,
        3: cv2.INTER_CUBIC,
        4: cv2.INTER_LANCZOS4
    }

    interpolation_method = interpolation_methods.get(2)

    timer = Timer('Frame')

    while not queue_manager.stop_event.is_set():
        timer.start()

        #queue_manager.frame_event.wait()

        try: 
            controls = queue_manager.control_frame_process.get_nowait()

            top = controls.get('top', 0)
            bottom = controls.get('bottom', 0)
            left = controls.get('left', 0)
            right = controls.get('right', 0)
            hl = controls.get('hl', 0)
            sl = controls.get('sl', 0)
            vl = controls.get('vl', 0)
            hm = controls.get('hm', 255)
            sm = controls.get('sm', 255)
            vm = controls.get('vm', 255)
            mode_image = controls.get('mode_image', 0)
            area_threshold = controls.get('area_threshold', 2600)
            #save_image = controls.get('save_image', False)
            snap_y = controls.get('snap_y', 200)
            processing = controls.get('processing', False)
            neuroun = controls.get('neuroun', True)
            y_delta = controls.get('y_delta', 37)
            x_delta = controls.get('x_delta', 21)
            x_min = controls.get('x_min', 120)
            x_max = controls.get('x_max', 700)
            dp = controls.get('dp', 1.2)
            minDist = controls.get('minDist', 20)
            param1 = controls.get('param1', 50)
            param2 = controls.get('param2', 42)
            minRadius = controls.get('minRadius', 22)
            maxRadius = controls.get('maxRadius', 45)
            height = controls.get('height', 250)
            #fps = controls.get('fps', 5)
            record_video = controls.get('record_video', False)
            #enable_process_camera = controls.get('enable_camera', True)
            k_size = controls.get('k_size', 1.0)
            method_index = controls.get('method_resize', 2)

            find_object_train = controls.get('find_object_train', False)
            
            interpolation_method = interpolation_methods.get(method_index)

            inizialization = True

        except Empty:
            if inizialization:
                pass
            else:
                continue

        # try:
        #     data_frame = queue_manager.frame_processor_queue.get_nowait()
        # except Empty:
        #     time.sleep(0.005)
        #     continue

        try:    
            data_frame = queue_manager.frame_processor_queue.get(timeout=21)
        except Empty:
            queue_manager.stop_event.set()


        #data_frame = queue_manager.frame_processor_queue.get()
        #queue_manager.frame_event.clear()
        #timer.start()
        
        #ygvstart_time = time.time()
        
        timestamp = data_frame['current_time']
        frame_id = data_frame['frame_id']

        id_memory = data_frame['id_memory']
        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        
        # if frames is None:
        #     queue_manager.memory_manager.release_memory("camera_data", id_memory)
            
        #     print('нет изображения в памяти с камеры')
        #     continue

        # if len(frames) == 0:
        #     queue_manager.memory_manager.release_memory("camera_data", id_memory)
            
        #     print('нет изображения в памяти с камеры')
        #     continue

        #frame = cv2.resize()

        # timer.start()

        frame = frames[0][top:bottom, left:right]
        # frame = cv2.imread('29.jpg')
        # frame = frame[:frame2.shape[0],:]

        #cv2.imwrite('test_camera.png', frame)
        
        frame_2 = frame.copy()
        frame_3 = frame.copy()
        hsv_bounds = (hl, sl, vl, hm, sm, vm)
        #frame_sub_mask, frame_mask, frame_mask_blurred = frame_detection.image_mask(frame_2, hsv_bounds)
        #frame_mask_bgr = cv2.cvtColor(frame_mask, cv2.COLOR_GRAY2BGR)


        # frame_mask_blurred_bgr = cv2.cvtColor(frame_mask, cv2.COLOR_GRAY2BGR)
        
        # timer.elapsed_time(print_log=True)

        total = 0

        old_frame_x_2 = []
        images_brak = []
        coordinates = []
        list_neuron = []
        batch_metadata = []
        batch_images = []


        if processing and not record_video:
            #frame_sub_mask = cv2.GaussianBlur(frame_sub_mask, (5, 5), 0)
            
            #frame_circl = frame_sub_mask[max(0, snap_y - height // 2):min(frame.shape[0], snap_y + height // 2), :]

            #frame_circl = frame[max(0, snap_y - height // 2):min(frame.shape[0], snap_y + height // 2), :]

            start_y = max(0, snap_y - height // 2)
            end_y = min(frame.shape[0], snap_y + height // 2)
            frame_circl = frame[start_y:end_y, :]

            frame_circl_hsv = cv2.cvtColor(frame_circl, cv2.COLOR_HSV2BGR)
            gray = cv2.cvtColor(frame_circl_hsv, cv2.COLOR_BGR2GRAY)

            #gray_blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp, minDist,
                                    param1=param1, param2=param2,
                                    minRadius=minRadius, maxRadius=maxRadius)

            if circles is not None:
                circles = np.round(circles[0, :]).astype("int")

                circles_sorted = sorted(circles, key=lambda x: x[1])

                x_prev = 0
                
                #print(old_frame_x_1)
                center = frame.shape[1] / 2

                offset_y = snap_y - height // 2

                for (x, y, r) in circles_sorted:
                    y_corrected = y + offset_y

                    if abs(y_corrected - snap_y) < y_delta and x >= x_min and x <= x_max:
                        if abs(x - x_prev) > x_delta:
                            delta_prev = True

                            for x_old, y_old, r_old in old_frame_x_1:
                                if (x <= center and -1 <= x - x_old <= 2) or (x > center and -2 <= x - x_old <= 1):
                                    if abs(y_corrected - y_old) > y_delta * 1.8 and abs(r - r_old) <= 4:
                                        delta_prev = False
                                        print(f"{x, y, r} -- {x_old, y_old, r_old}")
                                        break 

                            if not delta_prev:
                                continue

                            old_frame_x_2.append((x, y_corrected, r))

                            width = 72
                            height = 72

                            width_k = int(width * k_size)  // 2
                            height_k = int(height * k_size) // 2
                            #print(width_k, height_k)

                            img = frame[y_corrected - height_k: y_corrected + height_k, x - width_k: x + width_k]
                            img = cv2.resize(img, (72, 72), interpolation=interpolation_method)
                            #img = frame[y_corrected - 36 : y_corrected + 36, x - 36: x + 36]

                            if img.shape[0] == 72 and img.shape[1] == 72:
                                hsv_bounds_2 = (0, 0, 150, 179, 255, 255)
                                check_area, mask, total_area = frame_detection.filter_color_and_check_area(img, hsv_bounds_2, area_threshold)
                                
                                if find_object_train and is_color_area_above_threshold(img, target_color, 30):
                                    #print(f'синий {(x, y, r)}')
                                    check_area = True

                                #coordinates.append((x - r, y_corrected - r, 72, 72))
                                
                                #coordinates.append((x, y_corrected, r + 20, r + 20))

                                if check_area:
                                    coordinates.append((x, y_corrected, r + 10, r + 10))

                                    #print('total_area', total_area)
                                    
                                    batch_images.append(img)
                                    batch_metadata.append({
                                        'frame_id': frame_id,
                                        'x': x,
                                        'y': y_corrected,
                                        'r': r,
                                        'timestamp': timestamp,
                                        'total_area': total_area
                                    })
        
                                    # list_neuron.append((frame_id, img, x, y_corrected, r, timestramp))

                                    # total += 1
                                    # total_all += 1
                                    
                                    # if save_image:
                                    #     frame_detection.save_image_with_incremental_number(img, 'Neuron\Data_image\Image_all', '', '.jpg')

                                    #     save_info.append((frame_id, img, img_cnn, x, y, r, 'None', (255, 255, 255)))
                                # if save_image:
                                #     images_brak.append(img)

                        x_prev = x


            old_frame_x_1 = old_frame_x_2.copy()

            proccess_2 = False

            if proccess_2:          
                #frame_mask_blurred_bgr = cv2.cvtColor(frame_mask, cv2.COLOR_GRAY2BGR)

                #frame_square_mask_clear = frame_detection.overlay_image(frame_mask_bgr, (0, 0, 0), coordinates)
                frame_circl_mask_clear = frame_detection.draw_circles(frame_3, (220, 220, 220), coordinates)

                frame_sub_mask, frame_mask_2, frame_mask_blurred = frame_detection.image_mask(frame_circl_mask_clear, hsv_bounds, 2)

                if frame_mask_blurred is not None:
                    frame_mask_2_bgr = cv2.cvtColor(frame_mask_blurred, cv2.COLOR_GRAY2BGR)

                    frame_mask_clear =frame_mask_blurred [max(0, snap_y - y_delta):min(frame.shape[0], snap_y + y_delta), :]

                    other_coordinates, contours = frame_detection.find_counters(frame_mask_clear, 600, 2000, height_min=40)

                    offset_y_2 = snap_y - y_delta

                    # for contour in contours:
                    #     offset_contour = contour + (0, offset_y_2)
                    #     cv2.drawContours(frame_mask_2_bgr, [offset_contour], -1, (150, 255, 50), 2)

                    for contour in contours:
                        offset_contour = contour + (0, offset_y_2)
                        cv2.drawContours(frame_mask_2_bgr, [offset_contour], -1, (150, 255, 50), 2)
                        
                    for coordinate in other_coordinates:
                        # Рисуем точку в центре (с учётом смещения)
                        center_x, center_y = coordinate['center']
                        offset_center = (center_x, center_y + offset_y_2)  # Смещаем точку так же, как контур
                        cv2.circle(frame_mask_2_bgr, offset_center, 10, (0, 0, 255), -1) 

                    #print('other_coordinates', other_coordinates)

                    for coord in other_coordinates:
                        x = coord['center'][0]
                        y = coord['center'][1] 

                        y_corrected = y + offset_y_2

                        if abs(y_corrected - snap_y) < y_delta and x >= x_min and x <= x_max:
                            img = frame[y_corrected - 36 : y_corrected + 36, x - 36: x + 36]
                            #list_neuron.append((frame_id, img, x, y_corrected, coord['width'], timestamp))

                            batch_metadata.append({
                                            'frame_id': frame_id,
                                            'x': x,
                                            'y': y_corrected,
                                            'r': int(coord['height'] / 2),
                                            'timestamp': timestamp,
                                            'total_area': -999
                                        })
                        
                #cv2.imwrite('frame_circl_mask_clear.jpg', frame_circl_mask_clear)

                # frame_3[start_y:end_y, :] = frame_circl_mask_clear
                # frame_circl_mask_clear = frame_3

                #cv2.imwrite('frame_mask_2_bgr.jpg', frame_mask_2_bgr)

                # frame_4[start_y:end_y, :] = frame_mask_2_bgr
                # frame_mask_blurred_bgr = frame_4

            else:
                frame_mask_blurred_bgr = frame_2
                frame_circl_mask_clear = frame_2
                frame_sub_mask = frame_2
                frame_mask_2_bgr = frame_2


            # proccess_3 = False

            # if proccess_3:
            #     frame_mask_blurred_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            #     #frame_mask_blurred_bgr = cv2.cvtColor(frame_mask, cv2.COLOR_GRAY2BGR)

            #     #frame_square_mask_clear = frame_detection.overlay_image(frame_mask_bgr, (0, 0, 0), coordinates)
            #     frame_circl_mask_clear = frame_detection.draw_circles(frame_mask_blurred_bgr, (0, 0, 0), coordinates)

            #     frame_mask_clear = frame_circl_mask_clear[max(0, snap_y - y_delta):min(frame.shape[0], snap_y + y_delta), :]

            #     other_coordinates = frame_detection.find_counters(frame_mask_clear, 500, 2000)

            #     offset_y_2 = snap_y - y_delta

            #     for coord in other_coordinates:
            #         x = coord['center'][0]
            #         y = coord['center'][1] 

            #         y_corrected = y + offset_y_2

            #         if abs(y_corrected - snap_y) < y_delta and x >= x_min and x <= x_max:
            #             img = frame[y_corrected - 36 : y_corrected + 36, x - 36: x + 36]
            #             list_neuron.append((frame_id, img, x, y_corrected, coord['width'], timestamp))
            # else:
            #     frame_mask_blurred_bgr = frame_2
            #     frame_circl_mask_clear = frame_2



            #frame_mask_blurred_bgr = cv2.cvtColor(frame_mask_blurred, cv2.COLOR_GRAY2BGR)


        #frames = [frame_2, frame_sub_mask, frame_mask_bgr, frame_circl_mask_clear, frame_mask_blurred_bgr]

        frames = [frame_2, frame_circl_mask_clear, frame_sub_mask, frame_mask_2_bgr, frame_3]
        
        #print('frame process batch_images', len(batch_images), len(batch_metadata), 'id', id_memory)

        if len(frames) > 0:
            queue_manager.memory_manager.write_images(frames, "process_data", id_memory)


        if len(batch_images) > 0:
            queue_manager.memory_manager.write_images(batch_images, "neuroun_data", id_memory)

        
        data_frame['batch_metadata'] = batch_metadata

        

        #print(data_frame)

        queue_manager.remove_old_frame_if_full(queue_manager.neuroun_queue)
        queue_manager.neuroun_queue.put(data_frame)

      
        #queue_manager.neuroun_event.set()

        #timer.elapsed_time(print_log=True)
        #print(data_frame)
        
        # no_clear = False

        # if total == 0:
        #     coll_null_total += 1

        # if coll_null_total > 30:
        #     coll_null_total = 0

        #     for i in range(5):
        #         queue_manager.neural_input_queue.put('clear')

        #     p = 0
        #     while not stop_event.is_set()  and coll_clear <= 2:
        #         try:
        #             result_clear = queue_manager.neural_output_queue.get(timeout = 1)
        #         except Empty:
        #             print("Очередь neural_output_queue пуста")
        #             break
                
        #         if result_clear == 1:
        #             p += result_clear

        #         if p >= 5:
        #             print('Нейронки очищены')
        #             coll_clear += 1
        #             break

        
        # delay = calculate_delay(fps)

        # for img in images_brak:
        #     end_time = time.time()
        #     processing_time = (end_time - start_time) * 1000

        #     if processing_time <= delay - 50:
        #         frame_detection.save_image_with_incremental_number(img, r'C:\dev\Save_image', '', '.jpg')
        #     else:
        #         break
        
        # circles_info = []

        # if neuroun:
        #     try:
        #         result = queue_manager.neural_output_queue.get(timeout=1)

        #         if isinstance(result, list):
        #             circles_info = result   
        #         else:
        #             circles_info = []
        #     except Empty:
        #         print("Очередь neural_output_queue пуста")
        #         circles_info = []
                
            
        # end_time = time.time()
        # processing_time = (end_time - start_time) * 1000

        # result_data = {
        #     'frame': None,
        #     'frame_crop':  (top, bottom, left, right),
        #     'circles_info': circles_info,
        #     'processing_time': 0,
        #     'snap_y': snap_y,
        #     'y_delta': y_delta,
        #     'frame_id': frame_id,
        #     'total': total,
        #     'total_all': total_all,
        #     'x_min': x_min,
        #     'x_max': x_max,
        #     'timestrap': timestramp,
        #     'fps': timestramp,
        #     'delay': delay
        # }

        # match mode_image:
        #     case 0:
        #         frame = frame
        #     case 1:
        #         frame = frame_sub_mask
        #     case 2:
        #         frame = frame_mask_bgr
        #     case 3:
        #         frame = frame_circl_mask_clear
        #     case 4:
        #         frame_mask_blurred_bgr = cv2.cvtColor(frame_mask_blurred, cv2.COLOR_GRAY2BGR)
                

        #         for coord in other_coordinates:
        #             frame_mask_blurred_bgr = cv2.drawContours(frame_mask_blurred_bgr, coord['counter'] + np.array([[0, offset_y_2]]), -1, (0, 255, 255), 4)

        #         frame = frame_mask_blurred_bgr


        # combined_image = frame_detection.create_combined_image(frame, circles_info)
        # frame = frame_detection.add_black_space_below(frame, 8)
        # frame = frame_detection.combine_images_vertically(frame, combined_image)
            
        # if enable_process_camera:
        #     end_time = time.time()
        #     processing_time = (end_time - start_time) * 1000
        #     result_data['processing_time'] = processing_time

        #     frame = frame_detection.draw_on_frame(frame, result_data, controls)


        # # sleep_time = max(0, delay - processing_time) / 1000.0
        # # time.sleep(sleep_time)

        # # if not save_image:
        # #     time.sleep(sleep_time)
        
        # #queue_manager.camera_event.set()


        # result_data['frame'] = frame


        # queue_manager.clear_queue(queue_manager.result_frame_queue, 0)
        # queue_manager.result_frame_queue.put(result_data)

        # frame_id += 1

        # if frame_id >= 10:
        #     frame_id = 0

    print("Процессор завершен")
