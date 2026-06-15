
import json
from std_msgs.msg import String

from ai_controller.aicore.targetTracker import TrackDebugInfo

def _publish_inference(self, robot_name: str, t_dbg: TrackDebugInfo, g_dbg:str ):
    msg      = String()
    msg.data = json.dumps({
        "robot_name": robot_name,
        "state":      self.fsm.state.name,

        # GestureDebugInfo
        "gesture": g_dbg,

        # TrackDebugInfo
        "track": {
            "found":       t_dbg.found,
            "is_lost":     t_dbg.is_lost,
            "lost_frames": t_dbg.lost_frames,
            "box":         list(t_dbg.box)       if t_dbg.found else [],
            "torso_box":   list(t_dbg.torso_box) if t_dbg.torso_box else [],
            "cx":          t_dbg.cx              if t_dbg.found else 0,
            "cy":          t_dbg.cy              if t_dbg.found else 0,
            "h":           t_dbg.h               if t_dbg.found else 0,
            "h_ratio":     t_dbg.h_ratio         if t_dbg.found else 0.0,
            "track_id":    t_dbg.track_id        if t_dbg.found else -1,
            "sim":         t_dbg.sim             if t_dbg.found else 0.0,
        }
    })
    