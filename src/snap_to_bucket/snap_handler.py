#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = 'Siemens AG'

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
    """

    def __init__(self, bucket, tag="snap-to-bucket", verbose=0,
                 volume_type="gp2", storage_class="STANDARD",
                 mount_point="/mnt/snaps", delete_snap=False, restore=False,
                 restore_key="", restore_boot=False):
        """
        Initializer for the class attributes.

        :param bucket: Bucket to use
        :type bucket: string
        :param tag: Tag of snapshots for filtering
        :type tag: string
        :param verbose: Verbosity level (0-3)
        :type verbose: integer
        :param volume_type: Type of new EBS volume to use
        :type volume_type: string
        :param storage_class: Storage class of S3 object
        :type storage_class: string
        :param mount_point: Mount point to mount new volumes to
        :type mount_point: string
        :param delete_snap: True to delete snapshot after migration
        :type delete_snap: boolean
        :param restore: Is this a restore request?
        :type restore: boolean
        :param restore_key: Key of the tar to be restored
        :type restore_key: string
        :param restore_boot: Was the snapshot, being restored, bootable?
        :type restore_boot: boolean
        """
        self.__bucket = bucket
        self.__tag = tag
        self.__verbose = verbose
        if volume_type in ['standard', 'io1', 'gp2', 'sc1', 'st1']:
            self.__volume_type = volume_type
        else:
            raise Exception(f"Unrecognized volume type {volume_type} passed")
        if storage_class in ['STANDARD', 'REDUCED_REDUNDANCY', 'STANDARD_IA',
                             'ONEZONE_IA', 'GLACIER', 'INTELLIGENT_TIERING',
                             'DEEP_ARCHIVE']:
            self.__storage_class = storage_class
        else:
            raise Exception(f"Unrecognized storage class {storage_class} passed")
        self.__mount_point = mount_point
        self.__delete_snap = delete_snap
        self.__restore = restore
        self.__restore_key = restore_key
        self.__restore_boot = restore_boot
        self.__split_size = 5 * 1024.0 * 1024.0 * 1024.0 * 1024.0
        self.__gzip = False

    def update_proxy(self, proxy=None, noproxy=None):
        """
        Update the http_proxy and no_proxy environment variables
        """
        if proxy != None:
            os.environ['http_proxy'] = proxy
            os.environ['https_proxy'] = proxy
        else:
            if 'http_proxy' not in os.environ and 'HTTP_PROXY' in os.environ:
                os.environ['http_proxy'] = os.environ['HTTP_PROXY']
            if 'https_proxy' not in os.environ and 'HTTPS_PROXY' in os.environ:
                os.environ['https_proxy'] = os.environ['HTTPS_PROXY']
        if noproxy != None:
            os.environ['no_proxy'] = noproxy
        else:
            if 'no_proxy' not in os.environ and 'NO_PROXY' in os.environ:
                os.environ['no_proxy'] = os.environ['NO_PROXY']

        if 'no_proxy' in os.environ and "169.254.169.254" not in os.environ['no_proxy']:
            os.environ['no_proxy'] = os.environ['no_proxy'] + ",169.254.169.254"

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

    def initiate_migration(self):
        """
        The brains of the process
        """
        self.__ec2handler = Ec2Handler(self.__tag, self.__volume_type,
                                       self.__verbose)
        self.__s3handler = S3Handler(self.__bucket, self.__split_size,
                                     self.__gzip, self.__storage_class,
                                     self.__verbose)
        self.__fshandler = FsHandler(self.__mount_point, self.__verbose)
        os.makedirs(self.__mount_point, exist_ok=True)
        if self.__restore == True:
            if self.__restore_key == None:
                raise Exception("missing key argument for restore")
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
            except Exception as e:
                print("Error occurred during S3 upload for snapshot '" +
                      snapshot['id'] + "'", file=sys.stderr)
                print(f"Deleting volume '{volumeid}'", file=sys.stderr)
                self.__fshandler.unmount_volume()
                self.__ec2handler.detach_volume(volumeid)
                self.__ec2handler.delete_volume(volumeid)
                raise e
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
        :rtype: string
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
        :type size: integer
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
                                                          -1)
                self.__fshandler.untar(temp_path)
            else:
                for i in range(1, no_of_objects + 1):
                    temp_path = self.__s3handler.download_key(
                        self.__restore_key, i)
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
