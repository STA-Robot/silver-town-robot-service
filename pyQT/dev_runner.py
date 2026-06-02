# dev_runner.py
import sys
import os
import subprocess
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 감시할 대상 파일과 실행할 파이썬 인터프리터 경로 설정
TARGET_SCRIPT = "pyQT/QTlayout.py"
PYTHON_PATH = sys.executable  # 현재 가상환경의 python 경로를 자동으로 잡습니다.

class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.start_process()

    def start_process(self):
        """PyQt UI 프로세스 실행"""
        if self.process:
            self.process.terminate()  # 이미 실행 중인 창이 있으면 종료
            self.process.wait()
        
        print(f"코드가 변경되었습니다. {TARGET_SCRIPT} 재시작 중...")
        # 백그라운드로 PyQt 스크립트 실행
        self.process = subprocess.Popen([PYTHON_PATH, TARGET_SCRIPT])

    def on_modified(self, event):
        # 우리가 수정하는 특정 파일이 변경되었을 때만 재실행
        if os.path.basename(event.src_path) == TARGET_SCRIPT:
            # 순간적으로 저장이 여러 번 유입되는 것을 방지하기 위한 미세한 딜레이
            time.sleep(0.2)
            self.start_process()

if __name__ == "__main__":
    print(f"Live Reload 가동 시작: {TARGET_SCRIPT} 파일을 감시합니다.")
    
    event_handler = ReloadHandler()
    observer = Observer()
    # 현재 스크립트가 있는 디렉토리를 감시
    observer.schedule(event_handler, path=os.path.dirname(os.path.abspath(__file__)), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if event_handler.process:
            event_handler.process.terminate()
    observer.join()