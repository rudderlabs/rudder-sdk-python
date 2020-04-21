import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

# Don't import rudder_analytics module here, since deps may not be installed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rudder_analytics'))
from version import VERSION

long_description = '''
RudderStack is a platform for collecting, storing and routing customer event data to dozens 
of tools. RudderStack is open-source, can run in your cloud environment 
(AWS, GCP, Azure or even your data-centre) and provides a powerful transformation 
framework to process your event data on the fly.
'''

install_requires = [
    "requests>=2.7,<3.0",
    "six>=1.4",
    "monotonic>=1.5",
    "backoff==1.6.0",
    "python-dateutil>2.1"
]

tests_require = [
    "mock==2.0.0",
    "pylint==1.9.3",
    "flake8==3.7.9",
    "coverage==4.5.4"
]

setup(
    name='rudder-sdk-python',
    version=VERSION,
    url='https://github.com/rudderlabs/rudder-sdk-python',
    author='RudderStack',
    author_email='arnab@rudderlabs.com',
    maintainer='RudderStack',
    maintainer_email='arnab@rudderlabs.com',
    test_suite='rudder_analytics.test.all',
    packages=['rudder_analytics', 'rudder_analytics.test'],
    license='MIT License',
    install_requires=install_requires,
    keywords=['rudder', 'rudderstack', 'analytics'],
    extras_require={
        'test': tests_require
    },
    description='RudderStack is an open-source Segment alternative written in Go, built for the enterprise.',
    long_description=long_description,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
