std_msgs/Header header		# RMF가 생성한 명령 시각과 frame 정보
string robot_name		    # 명령 대상 로봇 이름. 예: pinky1
string command_id		    # 명령 고유 ID. DriveState에서 결과를 확인할 때 사용한다.
string command_type		    # 명령 종류. 예: navigate, returning, follow, stop
string map_name			    # RMF level 또는 map 이름. 예: L1

float64 x			    # 목표 위치 x 좌표. navigate/returning에서 사용한다.
float64 y			    # 목표 위치 y 좌표. navigate/returning에서 사용한다.
float64 yaw			    # 목표 방향 yaw. 라디안 단위이며 navigate/returning에서 사용한다.
float64 speed_limit		# 선택적 속도 제한. 사용하지 않으면 0.0

string target_name		# 목적지, 사람, station 등 사람이 읽기 쉬운 대상 이름
string payload_json		# command_type별 추가 인자. 필요 없으면 빈 문자열
