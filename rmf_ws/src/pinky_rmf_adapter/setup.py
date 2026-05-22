from glob import glob

from setuptools import setup


package_name = "pinky_rmf_adapter"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools", "nudged"],
    zip_safe=True,
    maintainer="ane",
    maintainer_email="ane@example.com",
    description="RMF fleet adapter for Pinky robots.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "fleet_adapter = pinky_rmf_adapter.pinky_fleet_adapter:main",
            "pinky_fleet_adapter = pinky_rmf_adapter.pinky_fleet_adapter:main",
            "pinky_task_orchestrator = pinky_rmf_adapter.pinky_task_orchestrator:main",
        ],
    },
)
