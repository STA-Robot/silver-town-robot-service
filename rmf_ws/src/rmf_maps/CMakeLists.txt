cmake_minimum_required(VERSION 3.8)
project(rmf_maps)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY maps nav_graphs
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
