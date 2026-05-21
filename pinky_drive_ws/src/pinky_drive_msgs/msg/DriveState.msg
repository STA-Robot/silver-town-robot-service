std_msgs/Header header	# 상태를 생성한 시각과 기준 frame 정보
string robot_name		# 상태를 publish하는 로봇 이름. 예: pinky1
string map_name			# 현재 로봇이 속한 RMF level 또는 map 이름. 예: L1

float64[3] pose		    # map frame 기준 현재 pose [x, y, yaw]
float32 battery_soc		# 배터리 잔량. 0.0 ~ 1.0 범위

string state			# 로봇의 공개 상태. 예: idle, navigating, returning, following, blocked, emergency
bool available			# 새 일반 명령을 받을 수 있는 상태인지 여부
bool emergency			# 비상정지 상태인지 여부

bool command_active		    # 현재 수행 중인 command가 있는지 여부
string active_command_id	# 현재 수행 중인 command_id. 없으면 빈 문자열
string last_command_id		# 마지막으로 상태가 기록된 command_id
string last_command_status	# 마지막 command 처리 결과. 예: accepted, succeeded, failed, rejected, canceled
string message			    # 사람이 읽을 수 있는 상태 설명 또는 오류 사유
