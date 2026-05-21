# pinky_drive_msgs/msg/DriveCommand.msg

std_msgs/Header header
string robot_name
string command_id
string command_type
string map_name

float64 x
float64 y
float64 yaw
float64 speed_limit

string target_name
string payload_json