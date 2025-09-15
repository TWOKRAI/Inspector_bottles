import csv
import numpy as np


Mask_dict = {}


data = [{
    'receipe': 'Blue cap blue bottle',
    'mask_cap_min': '0, 0, 0',
    'mask_cap_max': '145, 255, 255',
    'mask_level_min': '0, 0, 0',
    'mask_level_max': '95, 255, 255'
}, {
    'receipe': 'Red cap transperent bottle',
    'mask_cap_min': '0, 0, 0',
    'mask_cap_max': '255, 255, 255',
    'mask_level_min': '0, 0, 0',
    'mask_level_max': '255, 255, 255'
}]


with open('receipes.csv', 'w') as f:
    writer = csv.DictWriter(
        f, fieldnames=list(data[0].keys()), quoting=csv.QUOTE_NONNUMERIC)
    writer.writeheader()

    for d in data:
        writer.writerow(d)


with open('receipes.csv') as f:
    reader = csv.DictReader(f)

    for row in reader:
        Mask_dict[row['receipe']] = [row['mask_cap_min'], row['mask_cap_max'], 
                                     row['mask_level_min'], row['mask_level_max']]
        

print(Mask_dict)
print(np.array(Mask_dict[list(Mask_dict)[0]][0].split(', '), np.uint8))