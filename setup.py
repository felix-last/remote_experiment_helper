import os
from setuptools import setup
import io

def read(fname):
    return io.open(os.path.join(os.path.dirname(__file__), fname), encoding='utf-8').read()

setup(
    name='remote_experiment_helper',
    version="0.1.0",
    py_modules=['remote'],
    scripts=['bin/run_experiment', 'bin/setup_instance'],
    install_requires=[
        'boto3>=1.7,<1.10',
        'requests>=2.18,<2.23'
    ],
    author="Felix Last",
    author_email="mail@felixlast.de",
    url="https://github.com/felix-last/remote_experiment_helper",
    description=("Framework to  aid in running experiments inside docker containers on AWS(ish) instances."),
    long_description=read('README.rst'),
    license="MIT",
    keywords=[
        'Automation',
        'Infrastructure'
    ],
    classifiers=[]
)
