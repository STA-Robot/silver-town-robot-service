from loggerMixin import LoggerMixin
from followController import FollowController
"""
AI 서버 메시지 프로토콜:
    FOLLOW,cx,cy,h,id  → 정상 추적
    STOP               → 잠깐 소실 (9초 미만) → Recovery 안 함
    LOST               → 9초 이상 소실       → Recovery 탐색 시작
    END                → 60초 소실 / 종료    → done 발행
Returns:
    "done" — END 최초 진입 시
    None   — 그 외
"""

class StateHandler(LoggerMixin):
    def __init__(self, logger=None):
        self.set_logger(logger)
        self.controller = FollowController(logger=logger)
        self.prev_state = None

    def handle(self, msg, twist):

        parts = msg.strip().split(",")
        state = parts[0]
        event = None

        if state == "STOP":
            twist.linear.x  = 0.0
            twist.angular.z = 0.0
            self.controller.set_recovery(False)  # Recovery 비활성
            self._log_info("[STATE] STOP (잠깐 소실, 재감지 대기)")
            self.prev_state = "STOP"

        elif state == "LOST":
            twist.linear.x  = 0.0
            twist.angular.z = 0.0
            self.controller.set_recovery(True)   # Recovery 활성
            self._log_warn("[STATE] LOST → Recovery 탐색 시작")
            self.prev_state = "LOST"

        elif state == "END":
            twist.linear.x  = 0.0
            twist.angular.z = 0.0
            self._log_info("[STATE] END")

            if self.prev_state != "END":
                event = "done"

            self.prev_state = "END"
            self.controller.reset()   # Recovery 포함 전체 초기화
            return event

        elif state == "FOLLOW":
            try:
                cx       = int(parts[1])
                cy       = int(parts[2])
                h        = int(parts[3])
                track_id = int(parts[4])
            except (ValueError, IndexError):
                self._log_error(f"[FOLLOW] 파싱 실패: {msg}")
                return None

            # compute() 내부에서 set_recovery(False) 자동 호출
            linear, angular = self.controller.compute(cx, cy, h, track_id)
            twist.linear.x  = linear
            twist.angular.z = angular
            self.prev_state = "FOLLOW"

        else:
            self._log_warn(f"[STATE] 알 수 없는 상태: {state}")
            self.prev_state = state

        return event