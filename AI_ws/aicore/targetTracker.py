# aicore/targetTracker.py
from dataclasses import dataclass
from typing import Optional
from ultralytics import YOLO
import cv2
import numpy as np
from collections import defaultdict

TARGET_CLASS    = "doll"
REID_WEIGHT     = 0.6
COLOR_WEIGHT    = 0.4
MATCH_THRESHOLD = 0.45
LOST_MAX_FRAMES = 90
H_BINS          = 36
S_BINS          = 32
TORSO_RATIO     = (0.15, 0.65)

person_model = YOLO("models/doll_best.pt")


@dataclass
class TrackDebugInfo:
    found:       bool            = False
    cx:          int             = 0
    cy:          int             = 0
    h:           int             = 0
    track_id:    int             = 0
    sim:         float           = 1.0
    h_ratio:     float           = 0.0
    box:         Optional[tuple] = None
    torso_box:   Optional[tuple] = None
    lost_frames: int             = 0
    is_lost:     bool            = False


def extract_hs_histogram(frame, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    h_box = y2 - y1
    ty1   = y1 + int(h_box * TORSO_RATIO[0])
    ty2   = y1 + int(h_box * TORSO_RATIO[1])
    crop  = frame[ty1:ty2, x1:x2]
    if crop.size == 0:
        return None
    hsv  = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [H_BINS, S_BINS], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist.flatten()


def compare_hs_hist(h1, h2) -> float:
    if h1 is None or h2 is None:
        return 0.0
    dist = cv2.compareHist(
        h1.reshape(H_BINS, S_BINS),
        h2.reshape(H_BINS, S_BINS),
        cv2.HISTCMP_BHATTACHARYYA,
    )
    return max(0.0, 1.0 - dist)


def extract_reid_feat(results, box_idx):
    try:
        if hasattr(results, "feats") and results.feats is not None:
            feat = results.feats[box_idx]
            norm = np.linalg.norm(feat)
            return feat / norm if norm > 0 else feat
    except Exception:
        pass
    return None


def cosine_similarity(f1, f2) -> float:
    if f1 is None or f2 is None:
        return 0.0
    return float(np.dot(f1, f2))


class TargetTracker:
    def __init__(self):
        self.target_id      = None
        self.ref_color_hist = None
        self.ref_reid_feat  = None
        self.lost_frames    = 0
        self.id_history     = defaultdict(float)

    def reset(self):
        #ID + 특징 모두 초기화 
        self.target_id      = None
        self.ref_color_hist = None
        self.ref_reid_feat  = None
        self.lost_frames    = 0
        self.id_history     = defaultdict(float)
        print("[타겟 리셋] 완전 초기화")

    def soft_reset(self):
        #ID만 초기화, 특징 유지 (소실 후 재탐색 시 사용)
        self.target_id   = None
        self.lost_frames = 0
        self.id_history  = defaultdict(float)
        print("[타겟 소프트 리셋] ID 초기화, 특징 유지")

    def register(self, track_id, color_hist, reid_feat):
        self.target_id      = track_id
        self.ref_color_hist = color_hist
        self.ref_reid_feat  = reid_feat
        self.lost_frames    = 0
        print(f"[타겟 고정] ID={track_id}")

    def score(self, color_hist, reid_feat) -> float:
        c_sim = compare_hs_hist(self.ref_color_hist, color_hist)
        r_sim = cosine_similarity(self.ref_reid_feat, reid_feat)
        if self.ref_reid_feat is None:
            return c_sim
        if self.ref_color_hist is None:
            return r_sim
        return REID_WEIGHT * r_sim + COLOR_WEIGHT * c_sim

    def update_reference(self, color_hist, reid_feat, alpha=0.05):
        if color_hist is not None and self.ref_color_hist is not None:
            self.ref_color_hist = (1 - alpha) * self.ref_color_hist + alpha * color_hist
        if reid_feat is not None and self.ref_reid_feat is not None:
            blended = (1 - alpha) * self.ref_reid_feat + alpha * reid_feat
            norm    = np.linalg.norm(blended)
            self.ref_reid_feat = blended / norm if norm > 0 else blended


tracker = TargetTracker()


def get_person_target(frame) -> tuple[str, TrackDebugInfo]:
    results    = person_model.track(frame, persist=True)[0]
    debug      = TrackDebugInfo(lost_frames=tracker.lost_frames)
    best       = None
    best_area  = 0.0   #의미상 0.0 이 맞음 (area는 항상 양수)

    if results.boxes.id is not None:
        for idx, box in enumerate(results.boxes):
            if person_model.names[int(box.cls)] != TARGET_CLASS:
                continue
            if box.id is None:
                continue

            track_id = int(box.id)
            xyxy     = box.xyxy[0].tolist()
            x1, y1, x2, y2 = xyxy
            area     = (x2 - x1) * (y2 - y1)

            color_hist = extract_hs_histogram(frame, xyxy)
            reid_feat  = extract_reid_feat(results, idx)

            if tracker.target_id is None: # 등록 직후 → 이 박스가 타겟이므로 바로 best 후보에 넣기
                tracker.register(track_id, color_hist, reid_feat)
                sim = 1.0
                tracker.update_reference(color_hist, reid_feat)
            elif track_id == tracker.target_id:#이후 target_id같은지
                tracker.lost_frames = 0
                tracker.update_reference(color_hist, reid_feat)
                sim = 1.0
            else:
                sim = tracker.score(color_hist, reid_feat)
                tracker.id_history[track_id] += sim
                print(f"[유사도] ID:{track_id} sim={sim:.2f}")
                if sim >= MATCH_THRESHOLD:
                    old_id = tracker.target_id
                    tracker.register(track_id, color_hist, reid_feat)
                    print(f"[ID 교체] {old_id} → {track_id}  (유사도={sim:.2f})")
                else:
                    continue   # 다른 개체 — 무시

            if area > best_area:
                best_area = area
                best = (x1, y1, x2, y2, track_id, sim)

    if best is None:
        tracker.lost_frames += 1
        debug.lost_frames = tracker.lost_frames

        if tracker.lost_frames >= LOST_MAX_FRAMES:
            print(f"[타겟 소실] {LOST_MAX_FRAMES}프레임 미검출 → 소프트 리셋")
            tracker.soft_reset()   #특징 유지한 채 ID만 리셋 (재탐색 대비)
            debug.is_lost = True
            return "LOST", debug
        else:
            print(f"[None] TargetID:{tracker.target_id}  Lost({tracker.lost_frames}f)")
            return "None", debug

    x1, y1, x2, y2, track_id, sim = best
    cx      = int((x1 + x2) / 2)
    cy      = int((y1 + y2) / 2)
    h       = int(y2 - y1)
    h_ratio = h / frame.shape[0]

    ty1 = int(y1) + int(h * TORSO_RATIO[0])
    ty2 = int(y1) + int(h * TORSO_RATIO[1])

    debug.found     = True
    debug.cx        = cx
    debug.cy        = cy
    debug.h         = h
    debug.track_id  = track_id
    debug.sim       = sim
    debug.h_ratio   = h_ratio
    debug.box       = (int(x1), int(y1), int(x2), int(y2))
    debug.torso_box = (int(x1), ty1, int(x2), ty2)

    return f"{cx},{cy},{h},{track_id}", debug