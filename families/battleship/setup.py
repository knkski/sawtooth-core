import subprocess
from setuptools import setup, find_packages

setup(
    name='sawtooth-battleship',
    version=subprocess.check_output(['../../bin/get_version']).decode('utf-8').strip(),
    description='Sawtooth Battleship CLI',
    author='Hyperledger Sawtooth',
    url='https://github.com/hyperledger/sawtooth-core',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'battleship = sawtooth_battleship.cli:cli_wrapper',
        ]
    },
)