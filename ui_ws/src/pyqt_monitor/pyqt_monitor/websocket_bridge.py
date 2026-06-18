#!/usr/bin/env python3
"""
state_ws_bridge_node.py

/{robot_name}/state (DriveState) 구독 -> Unity RobotDTO와 동일한 키 구조의 JSON으로
변환해서 WebSocket으로 브로드캐스트하는 브릿지 노드.

Unity 쪽 RobotDTO:
    public string robot_name;
    public float  battery;
    public float  px, py, pz;
    public float  yaw;
    public string state;

필요 패키지:
    pip install websockets --break-system-packages
"""

import os
import json
import asyncio
import threading
import yaml
from ament_index_python.packages import get_package_share_directory
import websockets



# ----------------------------------------------------------------------
# WebSocket 서버 — 연결된 모든 Unity 클라이언트에 브로드캐스트
# ----------------------------------------------------------------------
class WebSocketBridge:

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def _handler(self, websocket):
        self.clients.add(websocket)
        print(f"[WS] 클라이언트 연결: {websocket.remote_address}")
        try:
            async for _ in websocket:
                pass  # Unity -> Python 방향은 현재 미사용
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"[WS] 클라이언트 종료: {websocket.remote_address}")

    async def _broadcast(self, payload: dict):
        if not self.clients:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send(msg)
            except websockets.exceptions.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def send_threadsafe(self, payload: dict):
        """ROS 콜백 스레드에서 호출 -> asyncio 루프로 안전하게 전달."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self.loop)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        async with websockets.serve(self._handler, self.host, self.port):
            print(f"[WS] 서버 시작: ws://{self.host}:{self.port}")
            await asyncio.Future()  # 영구 대기


def main():
    
    config_path = os.path.join(
        get_package_share_directory('visionDataHub'),
        'config', 'video_config.yaml'
    )
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    robot_configs = cfg["robots"]

    ws_bridge = WebSocketBridge(host="0.0.0.0", port=8765)

    def on_state(payload: dict):
        ws_bridge.send_threadsafe(payload)

    def on_offline(robot_name: str):
        ws_bridge.send_threadsafe({
            "robot_name": robot_name,
            "battery": 0.0,
            "px": 0.0,
            "py": 0.0,
            "pz": 0.0,
            "yaw": 0.0,
            "state": "offline",
        })

   

if __name__ == "__main__":
    main()