import cv2
from ultralytics import YOLO

# 1. 자체 학습된 커스텀 YOLO 모델 로드 (가중치 파일 경로 입력)
# 클래스 정의 예시: 0: 'palm'(멈춤), 1: 'thumbs-up'(팔로우), 2: 'fist'(팔로우 종료)
model = YOLO("best.pt") 

# 2. 웹캠 연결 (0번은 기본 내장/외장 카메라)
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# GUI 및 상태 안내를 위한 색상 정의 (BGR 순서)
COLOR_STOP = (0, 0, 255)      # 빨간색 (멈춤)
COLOR_FOLLOW = (0, 255, 0)    # 초록색 (팔로우)
COLOR_END = (255, 0, 0)       # 파란색 (팔로우 종료)
COLOR_TEXT = (255, 255, 255)  # 흰색

while cap.isOpened():
    success, frame = cap.read()
    if not success:
        print("카메라를 읽을 수 없습니다.")
        break

    # 3. YOLO 추론 (성능을 위해 confidence 임계값을 0.6으로 설정)
    results = model(frame, conf=0.6, verbose=False)
    
    # 초기 상태 정의
    current_status = "READY"
    gui_color = (128, 128, 128) # 기본 회색

    # 4. 검출된 객체 분석
    for result in results:
        boxes = result.boxes
        for box in boxes:
            cls_id = int(box.cls[0])
            label = model.names[cls_id]
            
            # 클래스별 상태 및 GUI 색상 매핑
            if label == "palm":
                current_status = "STOP (멈춤)"
                gui_color = COLOR_STOP
            elif label == "thumbs-up":
                current_status = "FOLLOW (팔로우)"
                gui_color = COLOR_FOLLOW
            elif label == "fist":
                current_status = "END FOLLOW (팔로우 종료)"
                gui_color = COLOR_END

            # 손 위치에 바운딩 박스 그리기
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(frame, (x1, y1), (x2, y2), gui_color, 3)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, gui_color, 2)

    # 5. 서버 화면용 상단 직관적 GUI 바(Bar) 생성
    # 화면 상단에 상태를 알리는 대형 사각형 배경을 그립니다.
    cv2.rectangle(frame, (0, 0), (1280, 80), gui_color, -1)
    cv2.putText(frame, f"ROBOT STATUS: {current_status}", (30, 55), 
                cv2.FONT_HERSHEY_DUPLEX, 1.5, COLOR_TEXT, 3, cv2.LINE_AA)

    # 6. 화면 출력 및 종료 조건 (q 누르면 종료)
    cv2.imshow("AI Server - Robot Gesture Control", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()