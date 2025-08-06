import cv2
import numpy as np

# Создание окна с трекбарами
cv2.namedWindow('Trackbars')
cv2.resizeWindow('Trackbars', 800, 400)

# Создание 6 трекбаров 
cv2.createTrackbar('H Min', 'Trackbars', 35, 179, lambda x: None)
cv2.createTrackbar('H Max', 'Trackbars', 85, 179, lambda x: None)
cv2.createTrackbar('S Min', 'Trackbars', 50, 255, lambda x: None)
cv2.createTrackbar('S Max', 'Trackbars', 255, 255, lambda x: None)
cv2.createTrackbar('V Min', 'Trackbars', 50, 255, lambda x: None)
cv2.createTrackbar('V Max', 'Trackbars', 255, 255, lambda x: None)

cv2.createTrackbar('Erode', 'Trackbars', 1, 10, lambda x: None)
cv2.createTrackbar('Dilate', 'Trackbars', 1, 10, lambda x: None)

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Получение значений трекбаров
    h_min = cv2.getTrackbarPos('H Min', 'Trackbars')
    h_max = cv2.getTrackbarPos('H Max', 'Trackbars')
    s_min = cv2.getTrackbarPos('S Min', 'Trackbars')
    s_max = cv2.getTrackbarPos('S Max', 'Trackbars')
    v_min = cv2.getTrackbarPos('V Min', 'Trackbars')
    v_max = cv2.getTrackbarPos('V Max', 'Trackbars')
    
    erode = cv2.getTrackbarPos('Erode', 'Trackbars')
    dilate = cv2.getTrackbarPos('Dilate', 'Trackbars')
    
    # Создание маски 
    lower_green = np.array([h_min, s_min, v_min])
    upper_green = np.array([h_max, s_max, v_max])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    
    mask = cv2.erode(mask, None, iterations=erode)
    mask = cv2.dilate(mask, None, iterations=dilate)

    # Поиск контуров
    contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Обработка контуров
    for contour in contours:
        if cv2.contourArea(contour) > 500:
            # Рисование контура
            cv2.drawContours(frame, [contour], -1, (0, 255, 0), 2)
            
            # Рисование прямоугольника
            x, y, w, h = cv2.boundingRect(contour)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
    
    # Отображение результата
    cv2.imshow('Green Detector', frame)
    cv2.imshow('Mask', mask)
    
    # Выход по 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()