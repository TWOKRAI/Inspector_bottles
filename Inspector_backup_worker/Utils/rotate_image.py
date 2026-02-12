from PIL import Image

# Открываем изображение
image = Image.open('App/Image/icons8-toggle-on-80.png')

# Переворачиваем изображение на 180 градусов
rotated_image = image.rotate(180)

# Сохраняем перевернутое изображение
rotated_image.save('App/Image/icons8-toggle-on-802.png')
