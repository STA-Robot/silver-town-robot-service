from dataclasses import dataclass
from typing import Optional
from ultralytics import YOLO
import cv2
import numpy as np
from collections import defaultdict


TARGET_CLASS    = "doll"
REID_WEIGHT     = 0.7          # ReID 비중 상향 (조명 영향 적음)
COLOR_WEIGHT    = 0.3          # 색상 비중 하향
MATCH_THRESHOLD = 0.40         # 약간 낮춤 (조명 변화 대응)
LOST_MAX_FRAMES = 90
LOST_END_FRAMES = 600
H_BINS          = 36
S_BINS          = 32

# ── [개선 1] doll은 가림 없으므로 전체 박스 사용
TORSO_RATIO     = (0.0, 1.0)

# ── [개선 2] 조명 정규화용 CLAHE 설정
CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))

# ── [개선 3] 크롭 최소 크기 기준
MIN_CROP_PX     = 15

import os
from ament_index_python.packages import get_package_share_directory

pkg_path   = get_package_share_directory('ai_controller')
model_path = os.path.join(pkg_path, 'models', 'doll_best.pt')

person_model = YOLO(model_path)


@dataclass
class TrackDebugInfo:
    found:             bool            = False
    cx:                int             = 0
    cy:                int             = 0
    h:                 int             = 0
    track_id:          int             = 0
    sim:               float           = 1.0
    h_ratio:           float           = 0.0
    box:               Optional[tuple] = None
    torso_box:         Optional[tuple] = None
    lost_frames:       int             = 0
    total_lost_frames: int             = 0
    is_lost:           bool            = False


# ──────────────────────────────────────────────
# [개선 1] 전체 박스 크롭 + 최소 크기 검증
# [개선 2] CLAHE로 V채널 조명 정규화 후 히스토그램 추출
# ──────────────────────────────────────────────
def extract_hs_histogram(frame, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    h_box = y2 - y1

    ty1 = y1 + int(h_box * TORSO_RATIO[0])
    ty2 = y1 + int(h_box * TORSO_RATIO[1])

    # 경계 클램핑
    ty1 = max(0, ty1)
    ty2 = min(frame.shape[0], ty2)
    x1  = max(0, x1)
    x2  = min(frame.shape[1], x2)

    crop = frame[ty1:ty2, x1:x2]

    # [개선 1] 크롭 최소 크기 검증 (작은 doll 대응)
    if crop.size == 0 or crop.shape[0] < MIN_CROP_PX or crop.shape[1] < MIN_CROP_PX:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # [개선 2] V채널에 CLAHE 적용 → 조명 변화 완화
    h_ch, s_ch, v_ch = cv2.split(hsv)
    v_ch = CLAHE.apply(v_ch)
    hsv  = cv2.merge([h_ch, s_ch, v_ch])

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
        self.target_id         = None
        self.ref_color_hist    = None
        self.ref_reid_feat     = None
        self.lost_frames       = 0
        self.total_lost_frames = 0
        self.id_history        = defaultdict(float)
        self.is_searching      = False

        # [개선 2] 조명 변화 대응: 히스토그램 이동 평균 유지
        self._hist_ema         = None   # Exponential Moving Average
        self._ema_alpha        = 0.15   # 낮을수록 과거 가중치 ↑

    def reset(self):
        self.target_id         = None
        self.ref_color_hist    = None
        self.ref_reid_feat     = None
        self.lost_frames       = 0
        self.total_lost_frames = 0
        self.id_history        = defaultdict(float)
        self.is_searching      = False
        self._hist_ema         = None
        print("[타겟 리셋] 완전 초기화")

    def soft_reset(self):
        self.target_id    = None
        self.lost_frames  = 0
        self.id_history   = defaultdict(float)
        self.is_searching = True
        # EMA 히스토그램은 유지 → 재탐색에 사용
        print("[타겟 소프트 리셋] ID 초기화, 특징 유지 (EMA 히스토그램 포함)")

    def register(self, track_id, color_hist, reid_feat):
        self.target_id         = track_id
        self.ref_color_hist    = color_hist
        self.ref_reid_feat     = reid_feat
        self.lost_frames       = 0
        self.total_lost_frames = 0
        self._hist_ema         = color_hist  # EMA 초기값
        print(f"[타겟 고정] ID={track_id}")

    # [개선 2] 추적 중 히스토그램을 EMA로 점진 갱신
    def update_hist_ema(self, color_hist):
        if color_hist is None:
            return
        if self._hist_ema is None:
            self._hist_ema = color_hist
        else:
            self._hist_ema = (
                self._ema_alpha * color_hist
                + (1.0 - self._ema_alpha) * self._hist_ema
            )

    def score(self, color_hist, reid_feat) -> float:
        # [개선 2] 비교 기준을 EMA 히스토그램으로 교체 (조명 적응)
        ref_hist = self._hist_ema if self._hist_ema is not None else self.ref_color_hist

        c_sim = compare_hs_hist(ref_hist, color_hist)
        r_sim = cosine_similarity(self.ref_reid_feat, reid_feat)

        if self.ref_reid_feat is None:
            return c_sim
        if ref_hist is None:
            return r_sim
        return REID_WEIGHT * r_sim + COLOR_WEIGHT * c_sim


tracker = TargetTracker()


def get_person_target(frame) -> tuple[str, TrackDebugInfo]:
    results   = person_model.track(frame, persist=True)[0]
    debug     = TrackDebugInfo(
        lost_frames=tracker.lost_frames,
        total_lost_frames=tracker.total_lost_frames,
    )
    best      = None
    best_area = 0.0

    if results.boxes.id is not None:
        for idx, box in enumerate(results.boxes):
            if person_model.names[int(box.cls)] != TARGET_CLASS:
                continue
            if box.id is None:
                continue

            track_id        = int(box.id)
            xyxy            = box.xyxy[0].tolist()
            x1, y1, x2, y2 = xyxy
            area            = (x2 - x1) * (y2 - y1)

            color_hist = extract_hs_histogram(frame, xyxy)
            reid_feat  = extract_reid_feat(results, idx)

            if tracker.target_id is None:
                if tracker.ref_color_hist is None and tracker._hist_ema is None:
                    # 완전 초기 상태 → 첫 박스 등록
                    tracker.register(track_id, color_hist, reid_feat)
                    sim = 1.0
                else:
                    # soft_reset 후 재탐색: EMA 포함 특징과 비교
                    sim = tracker.score(color_hist, reid_feat)
                    print(f"[재탐색] ID:{track_id} sim={sim:.2f}")
                    if sim >= MATCH_THRESHOLD:
                        tracker.target_id         = track_id
                        tracker.lost_frames       = 0
                        tracker.total_lost_frames = 0
                        tracker.is_searching      = False
                        tracker.update_hist_ema(color_hist)
                        print(f"[재탐색 성공] ID={track_id} (유사도={sim:.2f})")
                    else:
                        continue

            elif track_id == tracker.target_id:
                # 정상 수신: EMA 히스토그램 갱신
                tracker.lost_frames       = 0
                tracker.total_lost_frames = 0
                tracker.update_hist_ema(color_hist)   # [개선 2] 점진 갱신
                sim = 1.0

            else:
                sim = tracker.score(color_hist, reid_feat)
                print(f"[아이디 변경] ID:{track_id} sim={sim:.2f}")
                if sim >= MATCH_THRESHOLD:
                    tracker.target_id         = track_id
                    tracker.lost_frames       = 0
                    tracker.total_lost_frames = 0
                    tracker.update_hist_ema(color_hist)
                    print(f"re ID={track_id} (유사도={sim:.2f})")
                else:
                    continue

            if area > best_area:
                best_area = area
                best = (x1, y1, x2, y2, track_id, sim)

    if best is None:
        tracker.lost_frames       += 1
        tracker.total_lost_frames += 1
        debug.lost_frames          = tracker.lost_frames
        debug.total_lost_frames    = tracker.total_lost_frames

        if tracker.total_lost_frames >= LOST_END_FRAMES:
            tracker.reset()
            debug.is_lost = True
            return "END", debug

        if tracker.lost_frames >= LOST_MAX_FRAMES:
            tracker.soft_reset()
            debug.is_lost = True
            return "LOST", debug

        if tracker.is_searching:
            debug.is_lost = True
            return "LOST", debug

        return "STOP", debug

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

    return f"FOLLOW,{cx},{cy},{h},{track_id}", debug