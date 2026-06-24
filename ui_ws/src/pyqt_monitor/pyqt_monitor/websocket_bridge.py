
import asyncio
import json
import websockets

# WebSocket 서버

class WebSocketBridge:

    def __init__(self, host: str = "0.0.0.0", port: int = 8765,on_client_connected=None):
        self.host = host
        self.port = port
        self.unity_ip = None
        self.clients: set = set()
        self._on_client_connected = on_client_connected#-udo추가
        self.loop: asyncio.AbstractEventLoop | None = None

    async def _handler(self, websocket):
        self.clients.add(websocket)
        print(f"[WS] 연결: {websocket.remote_address}")
        unity_ip = websocket.remote_address[0]#-udo추가
 
        if self._on_client_connected:#-udo추가
            self._on_client_connected(unity_ip)
            print(f"[WSunity_ip] 연결: {unity_ip}")

        try:
            async for _ in websocket:
                pass  # Unity → Python 방향 현재 미사용
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"[WS] 종료: {websocket.remote_address}")

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
        #ROS 콜백 스레드 → asyncio 루프로 안전하게 전달.
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self.loop)

    async def run(self):
        print("[DEBUG] run() 진입") 
        self.loop = asyncio.get_running_loop()
        async with websockets.serve(self._handler, self.host, self.port):
            print(f"[WS] 서버 시작: ws://{self.host}:{self.port}")
            await asyncio.Future()


