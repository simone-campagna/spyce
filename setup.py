from setuptools import setup, find_packages


setup(
    name="spyce",
    version='0.1.0',  ## bumpversion!
    description="Add spices to python source files",
    author="Simone Campagna",
    url="",
    install_requires=[
        "pyyaml",
    ],
    package_dir={"": "src"},
    packages=find_packages(where='src'),
    entry_points={
        'console_scripts': [
                'spyce=spyce.tool:main_spyce',
        ],
    },
    classifiers=[],
)
