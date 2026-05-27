
class State:
    STOP   = "STOP"
    FOLLOW = "FOLLOW"
    END    = "END"

class Event:
    FOLLOW = "FOLLOW"
    STOP   = "STOP"
    END    = "END"
    NONE   = "NONE"

class StateController:
    def __init__(self):
        self.state    = State.STOP
        self._changed = False   # 이번 dispatch에서 전환 발생 여부

        self.transition = {
            State.STOP: {
                Event.FOLLOW: self._to_follow,
            },
            State.FOLLOW: {
                Event.STOP: self._to_stop,
                Event.END:  self._to_end,
            },
            State.END: {
                # 아무 이벤트도 받지 않음 — 종료 상태
            },
        }

    def dispatch(self, event: str) -> None:
        self._changed = False
        handler = self.transition.get(self.state, {}).get(event)#이벤트 유무 예)Event.FOLLOW
        if handler:
            handler()
            self._changed = True

    def did_change(self) -> bool:
        return self._changed

    # ── 전환 핸들러 
    def _to_follow(self):
        self.state = State.FOLLOW
        print(f"[FSM] → FOLLOW")

    def _to_stop(self):
        self.state = State.STOP
        print(f"[FSM] → STOP")

    def _to_end(self):
        self.state = State.END
        print(f"[FSM] → END")