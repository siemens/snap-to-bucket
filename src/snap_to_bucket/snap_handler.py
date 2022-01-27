#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = "Siemens AG"

import os
import sys

from snap_to_bucket import Ec2Handler
from snap_to_bucket import S3Handler
from snap_to_bucket import FsHandler


class SnapToBucket:
    """
    Main class of the tool

    :ivar bucket: Bucket to use
    :ivar tag: Tag of snapshots for filtering
    :ivar verbose: Verbosity level (0-3)
    :ivar volume_type: Type of new EBS volume to use
    :ivar storage_class: Storage class of S3 object
    :ivar mount_point: Mount point to mount new volumes to
    :ivar delete_snap: True to delete snapshot after migration
    :ivar restore: Is this a restore request?
    :ivar restore_key: Key of the tar to be restored
    :ivar restore_boot: Was the snapshot, being restored, bootable?
    :ivar split_size: Size in bytes to split tar at
    :ivar gzip: True to compress tar with gzip
    :ivar restore_dir: Location to store S3 object for restore
    :ivar iops: IOPS for supported volumes
    :ivar throughput: Throughput for supported volumes
    """

    def __init__(self, bucket, tag="snap-to-bucket", verbose=0,
                 volume_type="gp2", storage_class="STANDARD",
                 mount_point="/mnt/snaps", delete_snap=False, restore=False,
                 restore_key="", restore_boot=False,
                 restore_dir="/tmp/snap-to-bucket"):
        """
        Initializer for the class attributes.

        :param bucket: Bucket to use
        :type bucket: str
        :param tag: Tag of snapshots for filtering
        :type tag: str
        :param verbose: Verbosity level (0-3)
        :type verbose: int
        :param volume_type: Type of new EBS volume to use
        :type volume_type: str
        :param storage_class: Storage class of S3 object
        :type storage_class: str
        :param mount_point: Mount point to mount new volumes to
        :type mount_point: str
        :param delete_snap: True to delete snapshot after migration
        :type delete_snap: boolean
        :param restore: Is this a restore request?
        :type restore: boolean
        :param restore_key: Key of the tar to be restored
        :type restore_key: str
        :param restore_boot: Was the snapshot, being restored, bootable?
        :type restore_boot: boolean
        :param restore_dir: Location to store S3 object for restore
        :type restore_dir: str
        """
        self.__bucket = bucket
        self.__tag = tag
        self.__verbose = verbose
        if volume_type in ["standard", "io1", "gp2", "gp3", "sc1", "st1"]:
            self.__volume_type = volume_type
        else:
            raise Exception(f"Unrecognized volume type {volume_type} passed")
        if storage_class in ["STANDARD", "REDUCED_REDUNDANCY", "STANDARD_IA",
                             "ONEZONE_IA", "GLACIER", "INTELLIGENT_TIERING",
                             "DEEP_ARCHIVE"]:
            self.__storage_class = storage_class
        else:
            raise Exception(f"Unrecognized storage class {storage_class} passed")
        self.__mount_point = mount_point
        self.__delete_snap = delete_snap
        self.__restore = restore
        self.__restore_key = restore_key
        self.__restore_boot = restore_boot
        self.__restore_dir = restore_dir
        self.__split_size = 5 * 1024.0 * 1024.0 * 1024.0 * 1024.0
        self.__gzip = False
        self.__iops = None
        self.__throughput = None
        self.__ec2handler = None
        self.__s3handler = None
        self.__fshandler = None

    @staticmethod
    def update_proxy(proxy=None, noproxy=None):
        """
        Update the http_proxy and no_proxy environment variables
        """
        if proxy is not None:
            os.environ["http_proxy"] = proxy
            os.environ["https_proxy"] = proxy
        else:
            if "http_proxy" not in os.environ and "HTTP_PROXY" in os.environ:
                os.environ["http_proxy"] = os.environ["HTTP_PROXY"]
            if "https_proxy" not in os.environ and "HTTPS_PROXY" in os.environ:
                os.environ["https_proxy"] = os.environ["HTTPS_PROXY"]
        if noproxy is not None:
            os.environ["no_proxy"] = noproxy
        else:
            if "no_proxy" not in os.environ and "NO_PROXY" in os.environ:
                os.environ["no_proxy"] = os.environ["NO_PROXY"]

        if "no_proxy" in os.environ and "169.254.169.254" not in os.environ["no_proxy"]:
            os.environ["no_proxy"] = os.environ["no_proxy"] + ",169.254.169.254"

    def update_split_size(self, split):
        """
        Update the split size of tar

        :param split: New split size
        :type split: float
        """
        self.__split_size = split

    def perform_gzip(self):
        """
        Update the flag to compress tar with gzip
        """
        self.__gzip = True

    def update_iops(self, iops):
        """
        Update the IOPS of the volume

        :param iops: New IOPS value
        :type iops: int
        """
        self.__iops = int(iops)

    def update_throughput(self, throughput):
        """
        Update the throughput of the volume

        :param throughput: New throughput value
        :type throughput: int
        """
        self.__throughput = int(throughput)

    def initiate_migration(self):
        """
        The brains of the process
        """
        self.__ec2handler = Ec2Handler(self.__tag, self.__volume_type,
                                       self.__verbose, self.__iops,
                                       self.__throughput)
        self.__s3handler = S3Handler(self.__bucket, self.__split_size,
                                     self.__gzip, self.__storage_class,
                                     self.__verbose)
        self.__fshandler = FsHandler(self.__mount_point, self.__verbose)
        os.makedirs(self.__mount_point, exist_ok=True)
        if self.__restore is True:
            if self.__restore_key is None:
                raise Exception("missing key argument for restore")
            os.makedirs(self.__restore_dir, exist_ok=True)
            if not os.access(self.__restore_dir, os.W_OK):
                raise Exception(f"Directory {self.__restore_dir} is not writeable")
            self.__restore_snapshot()
            return

        snapshots = self.__ec2handler.get_snapshots()
        if len(snapshots) < 1:
            print(f"Unable to find snapshots with tag:{self.__tag}, value:migrate")
            return

        i = 1
        for snapshot in snapshots:
            print(f"Processing snapshot '{snapshot['id']}'")
            volumeid = self.__create_attach_volume(snapshot)
            try:
                self.__fshandler.mount_volume(volumeid)
                size = self.__fshandler.get_mounted_disc_size()
                self.__move_data(snapshot, size)
            except Exception as ex:
                print("Error occurred during S3 upload for snapshot '" +
                      snapshot["id"] + "'", file=sys.stderr)
                print(f"Deleting volume '{volumeid}'", file=sys.stderr)
                raise ex
            finally:
                self.__fshandler.unmount_volume()
                self.__ec2handler.detach_volume(volumeid)
                self.__ec2handler.delete_volume(volumeid)
            if self.__delete_snap:
                self.__ec2handler.delete_snapshot(snapshot)
            else:
                self.__ec2handler.update_snapshot_tag(snapshot)
            print(f"Processed snapshot '{snapshot['id']}'")
            print(f"{i} of " + str(len(snapshots)))
            i = i + 1

    def __create_attach_volume(self, snap):
        """
        Create and attach a new volume from given snapshot

        :param snap: Snapshot to be mounted
        :type snap: dict()

        :return: Newly created volume ID
        :rtype: str
        """
        volumeid = self.__ec2handler.create_volume(snap)
        self.__ec2handler.attach_volume(volumeid)
        return volumeid

    def __move_data(self, snapshot, size=0):
        """
        Upload the data from snapshot to S3

        :param snapshot: Snapshot to be uploaded
        :type snapshot: dict()
        :param size: Size of the mounted partition
        :type size: int
        """
        self.__s3handler.initiate_upload(snapshot, self.__mount_point, size)

    def __restore_snapshot(self):
        """
        Restore the snapshot from S3
        """
        (no_of_objects, size) = self.__s3handler.get_object_count_and_size(
            self.__restore_key)
        if no_of_objects > 0:
            volume_id = self.__ec2handler.create_empty_volume(size)
            self.__ec2handler.attach_volume(volume_id)
            self.__fshandler.prepare_volume(volume_id, self.__restore_boot)
            self.__fshandler.mount_volume(volume_id)
            if no_of_objects == 1:
                temp_path = self.__s3handler.download_key(self.__restore_key,
                                                        -1, self.__restore_dir)
                self.__fshandler.untar_single_file(temp_path)
            else:
                for i in range(1, no_of_objects + 1):
                    temp_path = self.__s3handler.download_key(
                        self.__restore_key, i, self.__restore_dir)
                    self.__fshandler.untar(temp_path)
            self.__fshandler.terminate_tar()
            if self.__restore_boot:
                self.__fshandler.update_fstab()
                self.__fshandler.mount_required_folders()
                self.__fshandler.update_grub(volume_id)
                self.__fshandler.unmount_volume()
                self.__fshandler.unmount_required_folders()
            else:
                self.__fshandler.unmount_volume()
            self.__ec2handler.detach_volume(volume_id)
