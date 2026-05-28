import time
from loggerMixin import LoggerMixin


class FollowController(LoggerMixin):
    def __init__(self, logger=None):
        self.set_logger(logger)

        #  각속도 P 제어 
        self.ANGULAR_GAIN = 0.0015
        self.DEAD_ZONE    = 20
        self.MAX_ANGULAR  = 0.20

        #  선속도 P 제어 
        self.Kp             = 1.0
        self.MAX_SPEED      = 0.15
        self.MIN_SPEED      = 0.05
        self.TARGET_H_RATIO = 0.80
        self.H_DEAD_ZONE    = 0.04

        # 회전 시 선속도 감쇠 
        self.ANGULAR_DAMPING = 0.7

        # 프레임 크기 
        self.FRAME_WIDTH  = 640
        self.FRAME_HEIGHT = 480

        #  타겟 추적 상태 
        self.target_id = None
        self.last_cx   = None  # Recovery 방향 판단용
        self.last_cy   = None

        # Recovery 
        # AI 서버가 LOST를 보낼 때만 활성화
        # STOP(잠깐 소실)일 때는 Recovery 안 함
        self.RECOVERY_ANGULAR  = 0.10   # 탐색 회전속도
        self._recovery_active  = False  # LOST 수신 시 True로 전환
        self._recovery_dir     = 1.0    # 마지막 위치 기반 방향

   

    def reset(self):
        
        self.target_id        = None
        self.last_cx          = None
        self.last_cy          = None
        self._recovery_active = False
        self._recovery_dir    = 1.0
        self._log_info("[FollowController] 상태 초기화")

    def set_recovery(self, active: bool):
        
        if active and not self._recovery_active:
            self._log_warn("[Recovery] 탐색 회전 시작")
        elif not active and self._recovery_active:
            self._log_info("[Recovery] 타겟 재발견 → 탐색 중단")
        self._recovery_active = active

    def compute(self, cx, cy, h, track_id):
        # 타겟 최초 고정
        if self.target_id is None:
            self.target_id = track_id
            self._log_info(f"[Target Lock] ID={track_id}")

        # AI ReID로 ID가 바뀐 경우 그대로 반영
        if track_id != self.target_id:
            self._log_info(f"[ID Update] {self.target_id} → {track_id} (ReID 반영)")
            self.target_id = track_id

        # Recovery 중이었다면 중단-> 계속들어갈수있음
        self.set_recovery(False)

        # 마지막 위치 갱신 (Recovery 방향 판단용)
        self.last_cx = cx
        self.last_cy = cy
        self._recovery_dir = 1.0 if cx < self.FRAME_WIDTH / 2 else -1.0

        # 각속도 계산 
        error_x = cx - (self.FRAME_WIDTH / 2)
        if abs(error_x) > self.DEAD_ZONE:
            raw     = -error_x * self.ANGULAR_GAIN
            angular = max(-self.MAX_ANGULAR, min(self.MAX_ANGULAR, raw))
        else:
            angular = 0.0

        # 선속도 계산 
        h_ratio = h / self.FRAME_HEIGHT
        error_h = self.TARGET_H_RATIO - h_ratio

        if error_h > self.H_DEAD_ZONE:
            raw    = self.Kp * error_h
            linear = max(self.MIN_SPEED, min(raw, self.MAX_SPEED))
        elif error_h < -self.H_DEAD_ZONE:
            raw    = self.Kp * error_h
            linear = max(-self.MAX_SPEED, min(raw, -self.MIN_SPEED))
        else:
            linear = 0.0

        # 회전 시 선속도 감쇠 
        if linear != 0.0 and angular != 0.0:
            angular_ratio = abs(angular) / self.MAX_ANGULAR
            linear       *= (1.0 - self.ANGULAR_DAMPING * angular_ratio)

        self._log_info(f"[FOLLOW] id={track_id} lin={linear:.2f} ang={angular:.3f}")
        return linear, angular

    def compute_recovery(self):
        #LOST 상태일 때 followerNode._check_timeout()에서 주기적으로 호출.
        if not self._recovery_active:
            return None

        if self.target_id is None:
            return None  # 아직 타겟 자체가 없음

        angular = self._recovery_dir * self.RECOVERY_ANGULAR # 타켓을 찾으면 바로 follow 메세지
        self._log_warn(
            f"[Recovery] 탐색 중 (dir={'←' if angular > 0 else '→'})"
        )
        return 0.0, angular