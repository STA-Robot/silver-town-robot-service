
import cv2
import numpy as np
from typing import Optional

from aicore.gestureRecognizer import GestureDebugInfo, GESTURE_COLOR
from aicore.targetTracker     import TrackDebugInfo

STATE_COLOR = {
    "STOP":   (0, 200, 255),
    "FOLLOW": (0, 220,   0),
    "END":    (0,   0, 220),
}

FONT      = cv2.FONT_HERSHEY_SIMPLEX
FONT_BOLD = cv2.FONT_HERSHEY_DUPLEX


def _text(img, txt, pos, scale=0.52, color=(255,255,255), thick=1, shadow=True):
    x, y = pos
    if shadow:
        cv2.putText(img, txt, (x+1, y+1), FONT, scale, (0,0,0), thick+1, cv2.LINE_AA)
    cv2.putText(img, txt, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def _filled_rect(img, pt1, pt2, color, alpha=0.55):
    x1, y1 = max(0, pt1[0]), max(0, pt1[1])   # 음수 좌표 클램핑
    x2, y2 = min(img.shape[1], pt2[0]), min(img.shape[0], pt2[1])
    if x1 >= x2 or y1 >= y2:
        return
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


def _progress_bar(img, x, y, w, h, ratio, fg_color, bg_color=(40,40,40)):
    cv2.rectangle(img, (x, y), (x+w, y+h), bg_color, -1)
    fill = max(0, int(w * min(ratio, 1.0)))
    if fill > 0:
        cv2.rectangle(img, (x, y), (x+fill, y+h), fg_color, -1)
    cv2.rectangle(img, (x, y), (x+w, y+h), (80,80,80), 1)


def draw(frame, state, gesture_dbg, track_dbg) -> np.ndarray:
    h_img, w_img = frame.shape[:2]
    cx_center    = w_img // 2

    cv2.line(frame, (cx_center, 0), (cx_center, h_img), (60, 60, 60), 1, cv2.LINE_AA)
    _draw_state_badge(frame, state, w_img)
    _draw_gesture(frame, gesture_dbg)
    _draw_track(frame, track_dbg, cx_center, h_img)
    return frame


def _draw_state_badge(img, state, w_img):
    color = STATE_COLOR.get(state, (160, 160, 160))
    bx1, by1 = w_img - 148, 0
    bx2, by2 = w_img, 38
    _filled_rect(img, (bx1, by1), (bx2, by2), color, alpha=0.75)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), color, 2)
    label_map = {"STOP": "STOP", "FOLLOW": "FOLLOW", "END": "END"}
    label = label_map.get(state, state)
    cv2.putText(img, label, (bx1 + 8, by1 + 26),
                FONT_BOLD, 0.62, (0, 0, 0), 2, cv2.LINE_AA)


def _draw_gesture(img, dbg: GestureDebugInfo):
    if dbg.label is None:
        _text(img, "No Gesture", (10, 28), scale=0.5, color=(120, 120, 120))
        return

    color = GESTURE_COLOR.get(dbg.label, (200, 200, 200))

    if dbg.box:
        x1, y1, x2, y2 = dbg.box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        tag   = f"{dbg.label} {dbg.conf:.0%}"
        tag_w = len(tag) * 9
        # 태그가 화면 위로 넘으면 박스 아래에 표시
        if y1 >= 22:
            _filled_rect(img, (x1, y1 - 22), (x1 + tag_w, y1), color, alpha=0.8)
            cv2.putText(img, tag, (x1 + 4, y1 - 6),
                        FONT, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        else:
            _filled_rect(img, (x1, y2), (x1 + tag_w, y2 + 22), color, alpha=0.8)
            cv2.putText(img, tag, (x1 + 4, y2 + 16),
                        FONT, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    _text(img, f"Gesture: {dbg.label}", (10, 26), scale=0.55, color=color)
    _progress_bar(img, 10, 32, 130, 8, dbg.conf, color)
    _text(img, f"{dbg.conf:.0%}", (145, 40), scale=0.42, color=color)


def _draw_track(img, dbg: TrackDebugInfo, cx_center: int, h_img: int):
    if not dbg.found and not dbg.is_lost and dbg.lost_frames == 0:
        return

    if dbg.is_lost:
        _filled_rect(img, (10, 55), (220, 88), (0, 0, 180), alpha=0.6)
        _text(img, "TARGET LOST", (18, 80), scale=0.7,
              color=(255, 255, 255), thick=2, shadow=False)
        return

    if not dbg.found:
        _text(img, f"Searching...  lost={dbg.lost_frames}f",
              (10, 75), scale=0.52, color=(0, 180, 255))
        return

    x1, y1, x2, y2 = dbg.box
    cx, cy          = dbg.cx, dbg.cy
    color_box       = (0, 230, 0)

    cv2.rectangle(img, (x1, y1), (x2, y2), color_box, 2, cv2.LINE_AA)

    if dbg.torso_box:
        tx1, ty1, tx2, ty2 = dbg.torso_box
        cv2.rectangle(img, (tx1, ty1), (tx2, ty2), (255, 80, 255), 1, cv2.LINE_AA)

    cv2.circle(img, (cx, cy), 5, (0, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 7, (255, 255, 255), 1, cv2.LINE_AA)

    tag   = f"ID:{dbg.track_id}  sim:{dbg.sim:.2f}"
    tag_w = len(tag) * 9
    _filled_rect(img, (x1, y2), (x1 + tag_w, y2 + 22), color_box, alpha=0.7)
    cv2.putText(img, tag, (x1 + 4, y2 + 16),
                FONT, 0.48, (0, 0, 0), 1, cv2.LINE_AA)

    panel_x = x1 - 160 if x1 > 165 else x2 + 6
    for i, (txt, col) in enumerate([
        (f"cx={cx}  cy={cy}",                (200, 200, 200)),
        (f"h={dbg.h}  ratio={dbg.h_ratio:.2f}", (200, 200, 200)),
        (f"err_x={cx - cx_center:+d}",
         (0, 200, 255) if abs(cx - cx_center) > 30 else (0, 230, 0)),
    ]):
        _text(img, txt, (panel_x, y1 + 18 + i * 20), scale=0.48, color=col)

    bar_y   = h_img - 22
    ratio   = min(dbg.h_ratio / 0.55, 1.0)
    b_color = (0, 0, 220) if dbg.h_ratio >= 0.55 else (0, 220, 0)
    _progress_bar(img, 10, bar_y, 160, 10, ratio, b_color)
    _text(img, "TOO CLOSE" if dbg.h_ratio >= 0.55 else "APPROACH OK",
          (176, bar_y + 9), scale=0.44,
          color=(0, 0, 220) if dbg.h_ratio >= 0.55 else (0, 220, 0))

    _draw_direction_arrow(img, cx_center, h_img, cx - cx_center)


def _draw_direction_arrow(img, cx_center, h_img, err_x, dead_zone=30):
    arrow_y   = h_img - 45
    arrow_len = 40

    if abs(err_x) <= dead_zone:
        pt1, pt2 = (cx_center, arrow_y + arrow_len), (cx_center, arrow_y)
        color = (0, 230, 0)
    elif err_x < 0:
        pt1 = (cx_center + arrow_len // 2, arrow_y + arrow_len // 2)
        pt2 = (cx_center - arrow_len // 2, arrow_y + arrow_len // 2)
        color = (0, 200, 255)
    else:
        pt1 = (cx_center - arrow_len // 2, arrow_y + arrow_len // 2)
        pt2 = (cx_center + arrow_len // 2, arrow_y + arrow_len // 2)
        color = (0, 200, 255)

    cv2.arrowedLine(img, pt1, pt2, (0, 0, 0), 5, cv2.LINE_AA, tipLength=0.35)
    cv2.arrowedLine(img, pt1, pt2, color,     2, cv2.LINE_AA, tipLength=0.35)