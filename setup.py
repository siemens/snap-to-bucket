#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""

import os
from setuptools import setup

__author__ = 'Siemens AG'


# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    """
    Utility function to read the README file.

    Parameters:
        fname (string): Path to file to read

    Returns:
        content (string): Content of the file
    """
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


metadata = dict(
    name="snap_to_bucket",
    version="1.0.0",
    author="Gaurav Mishra",
    author_email="mishra.gaurav@siemens.com",
    description=("Move AWS EBS Snapshots to S3 Buckets"),
    url = "https://github.com/siemens/snap-to-bucket/",
    license="MIT",
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Utilities",
        "Topic :: System :: Recovery Tools"
    ],
    keywords=[
        "aws", "snapshot", "bucket", "ebs", "s3"
    ],
    python_requires=">=3.5",
    package_dir={"": "src"},
    packages=["snap_to_bucket"],
    install_requires=[
        'boto3',
        'psutil'
    ],
    entry_points = {
        'console_scripts': [
            'snap_to_bucket = snap_to_bucket.run:entrypoint'
        ]
    },
)

setup(**metadata)
