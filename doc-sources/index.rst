.. snap_to_bucket documentation master file, created by
   sphinx-quickstart on Tue Apr  7 11:39:19 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

snap_to_bucket
==========================================

This tool allows to move data from AWS snapshots to S3 buckets.

Installation
=======================

.. code-block:: bash

    $ python3 -m pip install -U pipenv
    $ pipenv install --dev --editable .

Requirements
===============

#. The script needs to be running on an EC2 instance.

#. Minimum RAM 2 GB, recommend RAM > 6 GB.

#. The instance running the script must have IAM role attached with privileges
   to perform following operations:

    * List snapshot
    * Create volume
    * Attach volume
    * Delete volume
    * List S3 objects
    * Upload to S3
    * Download from S3

Sample IAM policy
====================

You can create an IAM role and attach following policy:

.. code-block:: JSON

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "ec2:DetachVolume",
                    "ec2:AttachVolume",
                    "ec2:ModifyVolume",
                    "ec2:DeleteSnapshot",
                    "ec2:ModifyVolumeAttribute",
                    "ec2:DescribeVolumesModifications",
                    "ec2:DescribeSnapshots",
                    "ec2:DescribeVolumeAttribute",
                    "ec2:CreateVolume",
                    "ec2:DeleteVolume",
                    "ec2:DescribeVolumeStatus",
                    "ec2:ModifySnapshotAttribute",
                    "ec2:DescribeVolumes",
                    "ec2:CreateTags",
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:AbortMultipartUpload",
                    "s3:GetObjectTagging",
                    "s3:PutObjectTagging",
                    "s3:HeadBucket",
                    "s3:ListMultipartUploadParts"
                ],
                "Resource": "*"
            }
        ]
    }

Disclaimer
=============

The tool works for snapshots with only one Linux partition. If there are more
than partition, only the first partition will be picked.

Similarly, only one partition will be created while restoring.

The script also does not encrypt your data explicitly. So, make sure the S3
bucket is secure enough and it is advisable to enable server-side encryption
with AES-256.

Options
==========

.. code-block::

    usage: snap_to_bucket [-h] [-v] -b BUCKET [--proxy PROXY] [--noproxy NOPROXY]
                          [-t TAG] [--type {standard,io1,gp2,gp3,sc1,st1}]
                          [--storage-class {STANDARD,REDUCED_REDUNDANCY,STANDARD_IA,ONEZONE_IA,GLACIER,INTELLIGENT_TIERING,DEEP_ARCHIVE}]
                          [-m DIR] [-d] [-s SIZE] [-g] [-r] [-k KEY] [--boot]
                          [--restore-dir RESTORE_DIR]

    snap_to_bucket is a simple tool based on boto3 to move snapshots to S3 buckets

    optional arguments:
      -h, --help            show this help message and exit
      -v, --verbose         increase output verbosity (-vvv for more verbosity)
      -b BUCKET, --bucket BUCKET
                            S3 bucket to push snaps in
      --proxy PROXY         proxy to be used
      --noproxy NOPROXY     comma separated list of domains which do not require
                            proxy
      -t TAG, --tag TAG     tag on snapshots (default: snap-to-bucket)
      --type {standard,io1,gp2,gp3,sc1,st1}
                            volume type (default: gp2)
      --storage-class {STANDARD,REDUCED_REDUNDANCY,STANDARD_IA,ONEZONE_IA,GLACIER,INTELLIGENT_TIERING,DEEP_ARCHIVE}
                            storage class for S3 objects (default: STANDARD)
      -m DIR, --mount DIR   mount point for disks (default: /mnt/snaps)
      -d, --delete          delete snapshot after transfer. Use with caution!
                            (default: False)
      -s SIZE, --split SIZE
                            split tar in chunks no bigger than (allowed suffix
                            b,k,m,g,t) (default: 5t)
      -g, --gzip            compress tar with gzip
      -r, --restore         restore a snapshot
      -k KEY, --key KEY     key of the snapshot folder to restore (required if
                            restoring)
      --boot                was the snapshot a bootable volume?
      --restore-dir RESTORE_DIR
                            directory to store S3 objects for restoring (default:
                            /tmp/snap-to-bucket)

See :ref:`migrate` for steps to migrate the EBS Snapshots to S3.

See :ref:`recovery` for steps to recover data from S3.

Files on S3
==============

The script will store snapshots with following structure in S3:
    ``snap/<snapshot-name>/<snapshot-id>-<creation-time>-<now-time>.tar``

The snaphost name gets spaces and ``/`` replaces as ``+`` and ``_`` respectively. And the date/time is in ISO 8601 format.

This section is controlled by ``get_key_for_upload()`` of ``S3Handler`` class.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   snap_to_bucket

   setupmigrate
   recovery


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
