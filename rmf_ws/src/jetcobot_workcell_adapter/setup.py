from glob import glob

from setuptools import setup


package_name = "jetcobot_workcell_adapter"

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
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ane",
    maintainer_email="ane@example.com",
    description="RMF ingestor bridge for JetCobot workcell commands.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "workcell_adapter = jetcobot_workcell_adapter.workcell_adapter:main",
        ],
    },
)
