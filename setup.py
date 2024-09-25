import sys
from setuptools import setup
from pathlib import Path

# Don't import rudder_analytics module here, since deps may not be installed
sys.path.insert(0, str(Path(__file__).resolve().parent / 'rudderstack' / 'analytics'))
from rudderstack.analytics.version import VERSION

long_description = (Path(__file__).resolve().parent / 'README.md').read_text(encoding='utf-8')

install_requires = [
    "requests>=2.32.3,<3.0",
    "monotonic>=1.6,<2.0",
    "backoff>=2.2.1,<3.0",
    "python-dateutil>=2.2,<3.0",
    "python-dotenv>=1.0.1,<2.0.0",
    "deprecation>=2.1.0,<3.0.0",
]

tests_require = [
    "mock==5.1.0",
    "flake8==7.1.1",
]

setup(
    name='rudder-sdk-python',
    version=VERSION,
    url='https://github.com/rudderlabs/rudder-sdk-python',
    author='RudderStack',
    author_email='sdk@rudderstack.com',
    maintainer='RudderStack',
    maintainer_email='sdk@rudderstack.com',
    packages=['rudderstack.analytics', 'rudderstack.analytics.test'],
    python_requires='>=3.8.0',
    license='MIT License',
    install_requires=install_requires,
    keywords=['rudder', 'rudderstack', 'analytics'],
    extras_require={
        'test': tests_require
    },
    description='RudderStack is an open-source Segment alternative written in Go, built for the enterprise.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    zip_safe=False,
    include_package_data=True,
)
