# ai_server.py (ReID + HSV 색상 기반 추적 버전)
# 밝기(V채널) 제외, Hue+Saturation 히스토그램으로 색상 특징 구성
# ReID 특징(외형 임베딩) + HSV(H+S) 색상 히스토그램 결합

import socket
import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict


#  ──네트워크 설정(테스트 고정값)──
LISTEN_IP   = "192.168.4.2"
LISTEN_PORT = 9999
PI_IP       = "192.168.4.1"
PI_PORT     = 9998

#  추적 파라미터
TARGET_CLASS      = "person"
REID_WEIGHT       = 0.6    # ReID 임베딩 유사도 가중치
COLOR_WEIGHT      = 0.4    # HSV 색상 유사도 가중치
MATCH_THRESHOLD   = 0.45   # 이 값 이상이어야 동일 인물로 판단
LOST_MAX_FRAMES   = 90     # 이 프레임 이상 미검출 시 타겟 소실 처리
H_BINS            = 36     # Hue 히스토그램 bins (360°/36 = 10°단위)
S_BINS            = 32     # Saturation 히스토그램 bins
TORSO_RATIO       = (0.15, 0.65)  # 박스 높이 기준 상체 영역 (상단 15%~65%)


#  ──모델 로드  (YOLOv8n → 내장 ReID 임베딩 추출 가능)──
model = YOLO("yolov8n.pt")

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.bind((LISTEN_IP, LISTEN_PORT))
recv_sock.settimeout(3.0)

send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"AI 서버 대기 중... {LISTEN_PORT}(수신) → Pi {PI_PORT}(송신)")

#  ──HSV 색상 특징 추출 (H + S 채널만 사용, V 제외)──
def extract_hs_histogram(frame, box):
 
    x1, y1, x2, y2 = [int(v) for v in box]
    h_box = y2 - y1

    # 상체 영역 자르기
    ty1 = y1 + int(h_box * TORSO_RATIO[0])
    ty2 = y1 + int(h_box * TORSO_RATIO[1])
    crop = frame[ty1:ty2, x1:x2]

    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # 2D 히스토그램: H × S (V 채널 완전 제외)
    hist = cv2.calcHist(
        [hsv], [0, 1],          # 채널 0=H, 1=S
        None,
        [H_BINS, S_BINS],
        [0, 180, 0, 256]        # H: 0~180, S: 0~256
    )
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist.flatten()

def compare_hs_hist(h1, h2):
   
    if h1 is None or h2 is None:
        return 0.0
    dist = cv2.compareHist(
        h1.reshape(H_BINS, S_BINS),
        h2.reshape(H_BINS, S_BINS),
        cv2.HISTCMP_BHATTACHARYYA
    )
    return max(0.0, 1.0 - dist)  # 비교 둘중에 큰값 리턴 /거리를 유사도로 변환 유사도 (1에 가까울수록 동일)

#  ──ReID 임베딩 추출 (YOLOv8 내장 feat 사용)──
def extract_reid_feat(results, box_idx):
    
    try:
        # ultralytics ≥8.1: results에 feats 속성 포함
        if hasattr(results, 'feats') and results.feats is not None:
            feat = results.feats[box_idx] #box_idx키로 벡터값가져오기 feats인텍스와 box_idx 대응한다
            norm = np.linalg.norm(feat) #벡터 길이계산
            return feat / norm if norm > 0 else feat  #길이를 1로 정규화
    except Exception:
        pass
    return None

def cosine_similarity(f1, f2):
    if f1 is None or f2 is None:
        return 0.0
    return float(np.dot(f1, f2))  # 이미 정규화된 벡터 코사인 유사도 (1 = 동일, 0 = 완전 다름)

#가시화 
def put_status(frame, text, line=0, color=(0, 0, 0)):
    y = 30 + line * 25  # line=0 → y=30, line=1 → y=55, line=2 → y=80
    cv2.putText(frame, text, (20, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
    
#  ──── 타겟 관리 클래스 ────
class TargetTracker:
    def __init__(self):
        self.target_id       = None   # YOLO 트랙 ID
        self.ref_color_hist  = None   # 기준 색상 히스토그램
        self.ref_reid_feat   = None   # 기준 ReID 임베딩
        self.lost_frames     = 0
        self.id_history      = defaultdict(float)  # ID별 누적 유사도

    def reset(self):
        self.target_id   = None
        self.lost_frames = 0
        self.id_history  = defaultdict(float)
        # ref_color_hist, ref_reid_feat 유지
        print("[타겟 리셋] ID만 초기화, 특징 유지")
        
    def register(self, track_id, color_hist, reid_feat):
        self.target_id      = track_id
        self.ref_color_hist = color_hist
        self.ref_reid_feat  = reid_feat
        self.lost_frames    = 0
        print(f"[타겟 고정] ID={track_id}")

    def score(self, color_hist, reid_feat):
        c_sim = compare_hs_hist(self.ref_color_hist, color_hist)
        r_sim = cosine_similarity(self.ref_reid_feat, reid_feat)

        if self.ref_reid_feat is None:
            # ReID 없으면 색상만 사용
            return c_sim
        if self.ref_color_hist is None:
            return r_sim

        return REID_WEIGHT * r_sim + COLOR_WEIGHT * c_sim #색상 + ReID 결합 유사도 계산 -판단 점수

    def update_reference(self, color_hist, reid_feat, alpha=0.05):
        #급격한 업데이트 방지 → alpha 작게 유지.
        if color_hist is not None and self.ref_color_hist is not None:
            self.ref_color_hist = (1 - alpha) * self.ref_color_hist + alpha * color_hist
        if reid_feat is not None and self.ref_reid_feat is not None:
            blended = (1 - alpha) * self.ref_reid_feat + alpha * reid_feat
            norm = np.linalg.norm(blended)
            self.ref_reid_feat = blended / norm if norm > 0 else blended

tracker = TargetTracker()

#  ──── 메인 루프 ────
while True:
    try:
        frame_bytes, addr = recv_sock.recvfrom(65507)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            continue

        results = model.track(frame, persist=True)[0] #persist=True->id추출

        debug_frame   = frame.copy()
        frame_center_x = frame.shape[1] // 2
        best          = None
        best_score    = -1.0

        if results.boxes.id is not None:
            for idx, box in enumerate(results.boxes):
                # ── 사람 클래스 필터 ──
                if model.names[int(box.cls)] != TARGET_CLASS:
                    continue
                if box.id is None:
                    continue

                track_id = int(box.id)
                xyxy     = box.xyxy[0].tolist()
                x1, y1, x2, y2 = xyxy
                area     = (x2 - x1) * (y2 - y1)

                # ── 특징 추출 ──
                color_hist = extract_hs_histogram(frame, xyxy)#색조,채도 비율얼마인지
                reid_feat  = extract_reid_feat(results, idx)#벡터 정규화한 값

                # ── 최초 타겟 등록 ──
                if tracker.target_id is None:
                    tracker.register(track_id, color_hist, reid_feat)

                # ── 타겟 ID와 일치 여부 검사 ──
                if track_id == tracker.target_id:
                   
                    tracker.lost_frames = 0
                    tracker.update_reference(color_hist, reid_feat)

                else:
                    # ID가 바뀌었을 때 ReID+색상으로 실제 동일인물인지 판단
                    sim = tracker.score(color_hist, reid_feat)
                    tracker.id_history[track_id] += sim
                    print(f"[유사도] ID:{track_id} sim={sim:.2f}")  

                    if sim >= MATCH_THRESHOLD:
                        # ID 교체 발생 (occlusion 후 재등장 등)
                        old_id = tracker.target_id
                        tracker.register(track_id, color_hist, reid_feat)
                        print(f"[ID 교체] {old_id} → {track_id}  (유사도={sim:.2f})") 
                    # ══════════════════════════════════════════════
                    # 다른 사람: 회색 박스 + 유사도 표시 -> 가시적 확인 필요 삭제 무관
                    else:
                        cv2.rectangle(debug_frame, (int(x1), int(y1)), (int(x2), int(y2)),
                                    (128, 128, 128), 1)
                        put_status(debug_frame, f"ID:{track_id} sim={sim:.2f}", line=0)
                        continue
                    # ══════════════════════════════════════════════
                   

                # ── 타겟 후보 중 가장 큰 박스 선택 ──
                if area > best_score:
                    best_score = area
                    best = (x1, y1, x2, y2, track_id, sim if track_id != tracker.target_id else 1.0)

        # ── 소실 카운터 ──
        if best is None:
            tracker.lost_frames += 1

            if tracker.lost_frames >= LOST_MAX_FRAMES:
                msg = "LOST"
                print(f"[타겟 소실] {LOST_MAX_FRAMES}프레임 미검출 → 자동 리셋")
                put_status(debug_frame, "LOST", line=0,color=(0, 0, 255))
                tracker.reset()
            else:
                msg = "None"
                label = "No Target" if tracker.target_id is None else \
                        f"ID:{tracker.target_id} Lost ({tracker.lost_frames}f)"
                put_status(debug_frame, label, line=0)
        else:
            tracker.lost_frames = 0
            x1, y1, x2, y2, track_id, sim = best
            cx      = int((x1 + x2) / 2)
            cy      = int((y1 + y2) / 2)
            h       = int(y2 - y1)
            h_ratio = h / frame.shape[0]
            error_x = cx - frame_center_x
            msg     = f"{cx},{cy},{h},{track_id}"
            
            # ══════════════════════════════════════════════가시화하는 코드 추후 삭제
            # 초록 박스 + 정보
            cv2.rectangle(debug_frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.circle(debug_frame, (cx, cy), 6, (0, 0, 255), -1)
            cv2.line(debug_frame, (frame_center_x, 0),
                     (frame_center_x, frame.shape[0]), (255, 0, 0), 1)
            put_status(debug_frame,f"track_ID:{track_id}  sim={sim:.2f}", line=1,color=(0, 0, 255))
            put_status(debug_frame,f"cx={cx} cy={cy} h={h}  h_ratio={h_ratio:.2f}", line=2)
            put_status(debug_frame,f"error_x={error_x}", line=3)
        
            status = "STOP (too close)" if h_ratio >= 0.55 else "MOVING FORWARD"
            color  = (0, 0, 255) if h_ratio >= 0.55 else (0, 255, 0)
            put_status(debug_frame,status, line=4)

            # 상체 추출 영역 시각화 (보라색)
            h_box = int(y2 - y1)
            ty1 = int(y1) + int(h_box * TORSO_RATIO[0])
            ty2 = int(y1) + int(h_box * TORSO_RATIO[1])
            cv2.rectangle(debug_frame, (int(x1), ty1), (int(x2), ty2), (255, 0, 255), 1)
            # ══════════════════════════════════════════════
        send_sock.sendto(msg.encode(), (PI_IP, PI_PORT))
        print(f"[송신→Pi] {msg}")

        cv2.imshow("AI Server - ReID+HS Tracking", debug_frame)

    except socket.timeout:
        print("[대기중] 신호 없음...")

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        tracker.reset()

recv_sock.close()
send_sock.close()
cv2.destroyAllWindows()