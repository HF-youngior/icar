# Third-party local dependencies

Do not commit third-party source trees or model files here.

For backend smoke/fire detection, each developer should prepare YOLOv5 locally at:

```text
third_party/yolov5-7.0/
```

The directory should contain files such as:

```text
third_party/yolov5-7.0/detect.py
third_party/yolov5-7.0/models/common.py
third_party/yolov5-7.0/utils/general.py
third_party/yolov5-7.0/requirements.txt
```

Then set:

```bash
export ICAR_HAZARD_YOLO_ROOT=third_party/yolov5-7.0
```
