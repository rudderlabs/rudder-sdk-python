import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

# Don't import rudder_analytics module here, since deps may not be installed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rudderstack', 'analytics'))
from rudderstack.analytics.version import VERSION

long_description = '''
RudderStack is a platform for collecting, storing and routing customer event data to dozens
of tools. RudderStack is open-source, can run in your cloud environment
(AWS, GCP, Azure or even your data-centre) and provides a powerful transformation
framework to process your event data on the fly.
'''

install_requires = [
    "requests>=2.8,<3.0",
    "monotonic>=1.5,<2.0",
    "backoff>=2.1,<3.0",
    "python-dateutil>=2.2,<3.0",
    "python-dotenv>=0.21.0,<0.22.0",
    "deprecation>=2.0.6,<3.0.0",
]

tests_require = [
    "mock==2.0.0",
    "pylint==2.8.0",
    "flake8==3.7.9",
]

setup(
    name='rudder-sdk-python',
    version=VERSION,
    url='https://github.com/rudderlabs/rudder-sdk-python',
    author='Rudderstack',
    author_email='sdk@rudderstack.com',
    maintainer='Rudderstack',
    maintainer_email='sdk@rudderstack.com',
    test_suite='rudderstack.analytics.test.all',
    packages=['rudderstack.analytics', 'rudderstack.analytics.test'],
    python_requires='>=3.6.0',
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
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
