# JetCobot MoveIt / Fast-CDR 트러블슈팅 기록

> **MoveIt**: ROS에서 로봇팔의 목표 자세까지 가는 경로를 planning하고 실행하는
> motion planning 프레임워크다. 이 프로젝트의 `arm_manager`는 MoveIt의
> `MoveGroup` action을 통해 joint target까지의 이동을 요청한다.

이 문서는 JetCobot Raspberry Pi에서 `jetcobot_driver`와 `arm_manager`를 실행할 때
발생했던 `moveit_msgs`, `Fast-CDR`, `FastRTPS` 관련 문제와 해결 순서를 기록한다.
다른 JetCobot에 같은 환경을 설치할 때 같은 증상이 재발할 수 있으므로, 아래 순서대로
확인한다.

> **Fast-CDR**: DDS가 ROS 메시지를 네트워크로 보내기 위해 객체를 바이트 배열로
> 직렬화/역직렬화할 때 쓰는 eProsima 라이브러리다. 실제 파일 이름은 보통
> `libfastcdr.so` 형태다.
>
> **FastRTPS / Fast-DDS**: ROS 2 노드 사이의 topic, service, action 통신을 실제로
> 수행하는 DDS 미들웨어 구현체다. FastRTPS는 예전 이름이고 Fast-DDS가 현재 이름에
> 가깝지만, ROS 패키지명에는 `fastrtps`가 여전히 많이 쓰인다.

## 환경

- OS: Ubuntu 24.04 Noble 계열
- ROS 2: Jazzy
- 실행 대상:
  - `jetcobot_driver trajectory_action_server`
  - `jetcobot_driver arm_manager`
- 관련 패키지:
  - `ros-jazzy-moveit-msgs`
  - `ros-jazzy-fastcdr`
  - `ros-jazzy-fastrtps`
  - `ros-jazzy-rmw-fastrtps-*`
  - `ros-jazzy-rosidl-typesupport-fastrtps-*`

## 증상 1: moveit_msgs 모듈 없음

`arm_manager` 실행 또는 빌드 중 아래와 비슷한 오류가 발생했다.

```text
ModuleNotFoundError: No module named 'moveit_msgs'
```

`arm_manager`는 MoveIt `MoveGroup` action을 사용하므로 `moveit_msgs`가 필요하다.

확인 명령:

```bash
source /opt/ros/jazzy/setup.bash
python3 -c "from moveit_msgs.action import MoveGroup; print('ok')"
```

설치 명령:

```bash
sudo apt update
sudo apt install -y ros-jazzy-moveit-msgs
```

## 증상 2: apt 404 또는 GPG key 오류

`ros-jazzy-moveit-msgs` 설치 중 오래된 apt 캐시나 만료된 ROS apt key 때문에
아래 문제가 발생할 수 있다.

```text
404 Not Found
```

또는:

```text
EXPKEYSIG F42ED6FBAB17C654 Open Robotics <info@osrfoundation.org>
The repository 'http://packages.ros.org/ros2/ubuntu noble InRelease' is not signed.
```

이 경우 먼저 apt 캐시와 ROS apt source/key 설정을 정리한다.

```bash
sudo apt clean
sudo rm -rf /var/lib/apt/lists/*
sudo apt update
```

ROS source가 중복 등록되어 있으면 `Signed-By` 충돌이 날 수 있다.

확인:

```bash
grep -R "packages.ros.org/ros2" \
  /etc/apt/sources.list \
  /etc/apt/sources.list.d/*.list \
  /etc/apt/sources.list.d/*.sources \
  2>/dev/null
```

중복된 ROS source가 있으면 백업 후 공식 `ros2-apt-source` 방식으로 다시 등록한다.

```bash
sudo mkdir -p /etc/apt/ros-source-backup

for f in /etc/apt/sources.list.d/*ros* /etc/apt/sources.list.d/*ROS*; do
  [ -e "$f" ] && sudo mv "$f" /etc/apt/ros-source-backup/
done

sudo mv /usr/share/keyrings/ros-archive-keyring.gpg \
  /etc/apt/ros-source-backup/ 2>/dev/null || true

sudo apt clean
sudo apt update
sudo apt install -y curl software-properties-common
sudo add-apt-repository -y universe

export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')

curl -L -o /tmp/ros2-apt-source.deb \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"

sudo dpkg -i /tmp/ros2-apt-source.deb
sudo apt clean
sudo apt update
```

이후 다시 설치한다.

```bash
sudo apt install -y ros-jazzy-moveit-msgs
```

## 증상 3: moveit_msgs import는 되지만 undefined symbol 발생

> **symbol**: `.so` 같은 공유 라이브러리 안에 들어 있는 함수나 변수 이름이다.
> C++ symbol은 컴파일러가 긴 내부 이름으로 바꾸기 때문에
> `_ZN8eprosima7fastcdr3Cdr9serializeEj`처럼 보일 수 있다.

`python3 -c "from moveit_msgs.action import MoveGroup; print('ok')"`는 성공했지만,
`arm_manager`에 명령을 publish하면 아래 오류가 발생했다.

```text
/usr/bin/python3: symbol lookup error:
/opt/ros/jazzy/lib/libmoveit_msgs__rosidl_typesupport_fastrtps_c.so:
undefined symbol: _ZN8eprosima7fastcdr3Cdr9serializeEj
```

이 심볼은 C++ demangle 기준으로 아래 함수다.

```text
eprosima::fastcdr::Cdr::serialize(unsigned int)
```

즉 `moveit_msgs`의 FastRTPS C typesupport가 기대하는 `libfastcdr` ABI와 현재 로드된
`libfastcdr`가 맞지 않는 상태다.

> **ABI**: 이미 컴파일된 바이너리끼리 맞춰야 하는 함수 이름, 인자, 메모리 배치,
> 호출 규칙 같은 약속이다. API가 소스코드 수준의 약속이라면 ABI는 `.so` 파일끼리
> 런타임에 맞아야 하는 약속이다. 패키지 버전이 섞이면 API import는 성공해도 ABI가
> 맞지 않아 undefined symbol이나 segfault가 날 수 있다.
>
> **typesupport**: ROS 메시지/action/service 타입을 특정 middleware가 송수신할 수
> 있도록 직렬화, 역직렬화, 타입 정보를 제공하는 ROS 생성 라이브러리다. 여기서는
> `libmoveit_msgs__rosidl_typesupport_fastrtps_c.so`가 MoveIt 메시지를 FastRTPS로
> 보내기 위한 C typesupport 라이브러리다.

### 1차 확인: Python import만으로는 부족하다

아래 import 테스트가 성공해도 native typesupport 로딩은 아직 검증되지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
python3 -c "from moveit_msgs.action import MoveGroup; print('ok')"
```

따라서 실제 문제가 난 라이브러리를 직접 로드해본다.

```bash
python3 - <<'PY'
import ctypes
ctypes.CDLL("/opt/ros/jazzy/lib/libmoveit_msgs__rosidl_typesupport_fastrtps_c.so")
print("typesupport cdll ok")
PY
```

여기서 undefined symbol이 나면 `moveit_msgs` 설치 여부가 아니라 Fast-CDR ABI 문제다.

### 2차 확인: libfastcdr가 해당 심볼을 제공하는지 확인

```bash
nm -D /opt/ros/jazzy/lib/libfastcdr.so.2 2>/dev/null \
  | grep '_ZN8eprosima7fastcdr3Cdr9serializeEj'
```

정상이라면 아래처럼 `T` 심볼이 보여야 한다.

```text
... T _ZN8eprosima7fastcdr3Cdr9serializeEj
```

심볼이 없으면 `ros-jazzy-fastcdr`가 너무 낡았거나 잘못 설치된 것이다.

해결:

```bash
sudo apt update
sudo apt install --only-upgrade -y ros-jazzy-fastcdr
sudo ldconfig
```

> **ldconfig**: Linux의 공유 라이브러리 검색 캐시를 갱신하는 명령이다. 새 `.so`
> 라이브러리를 설치하거나 버전을 바꾼 뒤 런타임 링커가 최신 라이브러리 위치를
> 인식하도록 `sudo ldconfig`를 실행한다.

업그레이드로 바뀌지 않으면 해당 패키지만 좁게 재설치한다.

```bash
sudo apt install --reinstall -y ros-jazzy-fastcdr
sudo ldconfig
```

### 3차 확인: 다른 libfastcdr를 잘못 로드하는지 확인

심볼이 `/opt/ros/jazzy/lib/libfastcdr.so.2`에 있는데도 실패하면, 런타임에 다른
`libfastcdr`가 먼저 로드되는 문제일 수 있다.

```bash
LD_DEBUG=libs python3 - <<'PY' 2>&1 | grep -E "libfastcdr|moveit_msgs"
import ctypes
ctypes.CDLL("/opt/ros/jazzy/lib/libmoveit_msgs__rosidl_typesupport_fastrtps_c.so")
PY
```

또는 직접 설치된 Fast-DDS/Fast-CDR 잔여물이 있는지 확인한다.

```bash
sudo find /usr/local /home -name "libfastcdr*" -o -name "libfastrtps*" 2>/dev/null
```

`/usr/local/lib/libfastcdr*` 같은 파일이 있으면 ROS 라이브러리를 가로챌 수 있다.
필요하면 임시로 비활성화한다.

```bash
sudo mkdir -p /usr/local/lib/disabled-fastdds
sudo mv /usr/local/lib/libfastcdr* /usr/local/lib/disabled-fastdds/ 2>/dev/null || true
sudo mv /usr/local/lib/libfastrtps* /usr/local/lib/disabled-fastdds/ 2>/dev/null || true
sudo ldconfig
```

다시 확인:

```bash
python3 - <<'PY'
import ctypes
ctypes.CDLL("/opt/ros/jazzy/lib/libmoveit_msgs__rosidl_typesupport_fastrtps_c.so")
print("typesupport cdll ok")
PY
```

## 증상 4: Fast-CDR 해결 후 launch에서 둘 다 segfault

`ros-jazzy-fastcdr`를 설치 또는 업그레이드한 뒤 `typesupport cdll ok`는 성공했지만,
launch 시 두 프로세스가 모두 `exit code -11`로 죽었다.

```text
[ERROR] [trajectory_action_server-1]: process has died ... exit code -11
[ERROR] [arm_manager-2]: process has died ... exit code -11
```

`trajectory_action_server`는 `moveit_msgs`를 사용하지 않으므로, 이 경우 문제는
`moveit_msgs` 단독이 아니라 DDS/FastRTPS/RMW 계열 패키지 버전이 서로 섞인 상태일
가능성이 높다.

> **DDS**: ROS 2가 노드 검색, topic publish/subscribe, action/service 통신을 위해
> 사용하는 표준 통신 계층이다. Fast-DDS/FastRTPS는 DDS 구현체 중 하나다.
>
> **RMW**: ROS Middleware interface의 약자다. ROS 2의 `rclpy`/`rclcpp`와 DDS 구현체
> 사이를 연결하는 추상화 계층이며, `rmw_fastrtps`는 FastRTPS/Fast-DDS를 쓰는 RMW
> 구현이다.

확인:

```bash
apt-cache policy \
  ros-jazzy-fastcdr \
  ros-jazzy-fastrtps \
  ros-jazzy-rmw-fastrtps-cpp \
  ros-jazzy-rmw-fastrtps-shared-cpp \
  ros-jazzy-rosidl-typesupport-fastrtps-c \
  ros-jazzy-rosidl-typesupport-fastrtps-cpp \
  ros-jazzy-rclpy \
  ros-jazzy-control-msgs \
  ros-jazzy-sensor-msgs \
  ros-jazzy-moveit-msgs
```

`fastcdr`만 새 빌드로 올라가고 `fastrtps`, `rmw_fastrtps`, `rosidl_typesupport_fastrtps`
계열이 오래된 빌드이면 런타임 ABI가 맞지 않아 segfault가 날 수 있다.

해결은 전체 ROS 재설치가 아니라, DDS/FastRTPS 계열을 같이 맞춰 업그레이드한다.

```bash
sudo apt update
sudo apt install --only-upgrade -y \
  ros-jazzy-fastcdr \
  ros-jazzy-fastrtps \
  ros-jazzy-rmw-fastrtps-cpp \
  ros-jazzy-rmw-fastrtps-shared-cpp \
  ros-jazzy-rosidl-typesupport-fastrtps-c \
  ros-jazzy-rosidl-typesupport-fastrtps-cpp

sudo ldconfig
```

## 최종 확인 절차

아래 순서가 모두 통과하면 launch를 다시 시도한다.

```bash
source /opt/ros/jazzy/setup.bash

python3 -c "from moveit_msgs.action import MoveGroup; print('moveit_msgs import ok')"

python3 - <<'PY'
import ctypes
ctypes.CDLL("/opt/ros/jazzy/lib/libmoveit_msgs__rosidl_typesupport_fastrtps_c.so")
print("moveit_msgs typesupport cdll ok")
PY

python3 - <<'PY'
import rclpy
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from moveit_msgs.action import MoveGroup
from jetcobot_workcell_msgs.msg import WorkcellCommand, WorkcellState

rclpy.init()
node = rclpy.create_node("jetcobot_ros_smoke_test")
print("rclpy + msgs ok")
node.destroy_node()
rclpy.shutdown()
PY
```

workspace source 순서는 항상 ROS base를 먼저, workspace overlay를 나중에 한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/jetcobot/sgoh/install/setup.bash
```

launch:

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  port:=/dev/ttyJETCOBOT \
  use_arm_manager:=true \
  arm_name:=jetcobot1
```

## 참고: MoveGroup을 쓰지 않는 우회 경로

현재 MVP의 `arm_manager.yaml`은 joint waypoint 기반 smoke sequence다. 따라서
MoveIt `MoveGroup` 대신 아래 action으로 직접 명령을 보내는 backend를 만들면
`moveit_msgs`와 `move_group` 의존성을 피할 수 있다.

```text
/arm_controller/follow_joint_trajectory
/gripper_controller/follow_joint_trajectory
```

장점:

- Pi 런타임 의존성이 단순해진다.
- `moveit_msgs` / Fast-CDR ABI 문제를 피할 수 있다.
- 현재 smoke test에는 충분하다.

단점:

- MoveIt planning, 충돌 회피, planning scene을 사용하지 않는다.
- 목표 joint 각도와 중간 경로 안전성을 사람이 검증해야 한다.
- 나중에 카메라 기반 object pose로 end-effector를 이동하는 기능은 MoveIt 쪽이 유리하다.

현재 단계에서는 MoveIt 환경이 안정되면 `MoveGroup` backend를 유지하고, 불안정한 Pi에서는
직접 `FollowJointTrajectory` backend를 옵션으로 두는 방식이 현실적이다.
