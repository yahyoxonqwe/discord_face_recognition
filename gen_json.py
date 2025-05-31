import os
from scrfd import SCRFD
from arcface_onnx import ArcFaceONNX
from collections import defaultdict
import cv2
import json
import imghdr

database_folder = f'./dataset'

det_model = "./models/buffalo_s/det_500m.onnx"
rec_model = "./models/buffalo_s/w600k_mbf.onnx"

detector = SCRFD(det_model)
detector.prepare(1)

rec = ArcFaceONNX(rec_model)
rec.prepare(1)


database = defaultdict(list)
for person_name in os.listdir(database_folder):
    
    person_path = os.path.join(database_folder, person_name)
    print(person_path)
    if os.path.isdir(person_path):
        for image_file in os.listdir(person_path):
            print(image_file)
            image_path = os.path.join(person_path, image_file)
            if imghdr.what(image_path) is None:
                continue
            img = cv2.imread(image_path)  ##### shuni qarab ko'rish kerak 
            
            # Perform face detection
            bboxes, kpss = detector.autodetect(img , max_num=1)

            if bboxes.shape[0]==0:
                continue

            kps = kpss[0]
            feat = rec.get(img, kps)
#            print(feat.shape)
            database[person_name].append(feat.tolist())

with open("./employees.json", "w") as json_file:
    json.dump(database, json_file)
