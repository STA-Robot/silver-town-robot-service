# Pinky follower 

FollowerNode는 UDP로 전달받은 AI 추적 결과를 기반으로 로봇을 제어하는 ROS2 노드입니다.

UDP → 사람 추적 결과 수신
상태 기반 제어 → cmd_vel 발행
follow 시작/종료 이벤트 처리
timeout 및 recovery 처리 포함

##  구조

```text
src/
  follower_node/        
```

## 사전 조건

- Pinky패키지에  ros2 launch pinky_bringup bringup_robot.launch.xml


## 실행

ros2 run Pinky_follower follower_node

