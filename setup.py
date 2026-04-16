from setuptools import setup, find_packages

setup(
    name="adeval",
    version="0.3.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "adeval": ["static/*", "static/css/*", "static/js/*"],
    },
    install_requires=[
        "fastapi",
        "uvicorn",
        "requests",
        "typer",
        "pydantic",
    ],
    entry_points={
        "console_scripts": [
            "adeval=adeval.cli:cli",
        ],
    },
)
