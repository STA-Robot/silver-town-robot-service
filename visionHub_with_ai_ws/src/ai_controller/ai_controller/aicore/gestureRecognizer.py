from dataclasses import dataclass
from typing import Optional
from collections import deque, Counter
from ultralytics import YOLO
from ..stateController import Event
import os
from ament_index_python.packages import get_package_share_directory

pkg_path = get_package_share_directory('ai_controller')
model_path = os.path.join(pkg_path, 'models', 'gesture_best.pt')
gesture_model = YOLO(model_path)

GESTURE_MAPPING = {
    "Paper":    Event.STOP,
    "Rock":     Event.END,
    "Scissors": Event.FOLLOW,
}
 
CONF_THRESHOLD = 0.60

# 투표 설정- 순시간에 지나가는 제스처 무시 3프레임 까지 같은 동작
VOTE_WINDOW    = 5   # 최근 몇 프레임을 볼 것인가
VOTE_MIN_AGREE = 3   # 그 중 몇 번 일치해야 확정할 것인가
 
_vote_history: deque = deque(maxlen=VOTE_WINDOW)# (Event, GestureDebugInfo) 저장

def get_gesture(frame) -> Event:
    
    results = gesture_model(frame, conf=0.6, iou=0.6, verbose=False)[0]
    
    # debug   = GestureDebugInfo()
 
    if len(results.boxes) == 0:
        _vote_history.append((Event.NONE))
        return Event.NONE
 
    best_box = max(results.boxes, key=lambda b: float(b.conf))
    conf     = float(best_box.conf)
 
    #임계값 미만이면 감지 무시
    if conf < CONF_THRESHOLD:
        _vote_history.append((Event.NONE))
        return Event.NONE
 
    cls_id = int(best_box.cls[0])
    label = gesture_model.names[cls_id]

    raw_event = GESTURE_MAPPING.get(label, Event.NONE)
    _vote_history.append((raw_event)) 

    event_counts = Counter(e for e, _ in _vote_history)
    top_event, top_cnt = event_counts.most_common(1)[0]

    if top_event != Event.NONE and top_cnt >= VOTE_MIN_AGREE:
        # 확정된 이벤트에 해당하는 debug 중 가장 최신 것을 반환
        return top_event

    return Event.NONE