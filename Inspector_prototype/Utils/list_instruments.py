def divide_list(input_list, num_parts, additional_elements=0):
    # Проверяем, что additional_elements не превышает длину списка
    if additional_elements > len(input_list):
        additional_elements = len(input_list)

    # Выделяем дополнительные элементы из начала списка
    additional_elements_list = input_list[:additional_elements]
    remaining_list = input_list[additional_elements:]

    # Определяем количество элементов в каждой части
    total_elements = len(remaining_list)
    base_size = total_elements // num_parts
    remainder = total_elements % num_parts

    # Создаем список для хранения частей
    parts = []

    start = 0
    for i in range(num_parts):
        end = start + base_size + (1 if i < remainder else 0)
        parts.append(remaining_list[start:end])
        start = end

    # Если элементов меньше чем частей, добавляем пустые списки
    while len(parts) < num_parts:
        parts.append([])

    # Добавляем дополнительные элементы в первый список
    if parts:
        parts[0] = additional_elements_list + parts[0]

    return parts


def generate_lists(n):
    return [[1] for _ in range(n)]


if __name__ == "__main__":
    while True:
        print()
        num_list = int(input('Количество элементов: '))

        print()
        test_list = generate_lists(num_list)

        coll_part =  int(input('Сколько частей: '))

        test = divide_list(test_list, coll_part, 1)

        print(test)

