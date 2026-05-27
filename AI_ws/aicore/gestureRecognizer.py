from dataclasses import dataclass
from typing import Optional
from ultralytics import YOLO
from control.stateContoller import Event

gesture_model = YOLO("models/gesture_best.pt")

GESTURE_MAPPING = {
    "Paper":    Event.STOP,
    "Rock":     Event.END,
    "Scissors": Event.FOLLOW,
}
 
# 제스처별 표시 색상 (BGR)
GESTURE_COLOR = {
    "Scissors": (0,   220,   0),   # 초록  — FOLLOW
    "Paper":    (0,   200, 255),   # 노랑  — STOP
    "Rock":     (0,     0, 220),   # 빨강  — END
}
CONF_THRESHOLD = 0.70

@dataclass
class GestureDebugInfo:
    label:  Optional[str]          = None   # 감지된 제스처명
    conf:   float                  = 0.0    # 신뢰도
    box:    Optional[tuple]        = None   # (x1, y1, x2, y2) 정수

def get_gesture(frame) -> tuple[str, GestureDebugInfo]:
    results = gesture_model(frame, verbose=False)[0]
    debug   = GestureDebugInfo()
 
    if len(results.boxes) == 0:
        return Event.NONE, debug
 
    best_box = max(results.boxes, key=lambda b: float(b.conf))
    conf     = float(best_box.conf)
 
    #임계값 미만이면 감지 무시
    if conf < CONF_THRESHOLD:
        return Event.NONE, debug
 
    cls_id        = int(best_box.cls[0])
    label         = gesture_model.names[cls_id]
    x1, y1, x2, y2 = best_box.xyxy[0].tolist()
 
    debug.label = label
    debug.conf  = conf
    debug.box   = (int(x1), int(y1), int(x2), int(y2))
 
    return GESTURE_MAPPING.get(label, Event.NONE), debug