#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = 'Siemens AG'

import os
import re
import sys
import time
import json
import subprocess
from subprocess import PIPE, Popen

import psutil


class FsHandler:
    """
    Class to handle communications with local file system

    :ivar mount_point: Mount point to be used for devices
    :ivar verbose: Verbosity level (0-3)
    :ivar device: The device to be mounted
    """

    TEN_MB = 10 * (1024 ** 2)

    def __init__(self, mount_point, verbose=0):
        """
        Initializer for the class attributes.

        :param mount_point: Mount point to use
        :type mount_point: string
        :param verbose: Verbosity level (0-3)
        :type verbose: integer
        """
        self.mount_point = mount_point
        self.verbose = verbose
        self.untar_process = None

    def __wait_for_device_settle(self):
        """
        Wait for device to settle

        Calls ``partprobe`` and ``udevadm settle``
        """
        subprocess.call(["partprobe"])
        subprocess.call(["udevadm", "settle"])
        time.sleep(5)

    def __get_mbr_device_name(self, volumeid):
        """
        Get the name of mounted device containing MBR record to be updated

        Lists all the devises by lsblk and check the device with label=volumeid.
        If the device has an child mounted to mount_point, select the parent
        device as MBR device otherwise select current device.

        :param volumeid: The volume to search
        :type volumeid: string

        :return: Device with MBR to be updated
        :rtype: string

        :raises Exception: If none devices can be found
        """
        lsblk_process = Popen(["lsblk", "--json", "--output",
                               "NAME,SERIAL,MOUNTPOINT"], stdout=PIPE)
        result = lsblk_process.communicate()[0].decode('UTF-8').strip()
        devices = json.loads(result)
        blk_device = None
        volume_serial = volumeid.replace('-', '')
        for device in devices['blockdevices']:
            if device['serial'] == volume_serial:
                if 'children' in device:
                    for child in device['children']:
                        if child['mountpoint'] == self.mount_point:
                            blk_device = "/dev/" + device['name']
                            break
                if blk_device == None:
                    blk_device = "/dev/" + device['name']
                break
        if blk_device == None:
            raise Exception
        return blk_device

    def __update_device_name(self, volumeid):
        """
        Get the name of device which can be mounted

        Lists all the devises by lsblk and check the device with label=volumeid.
        If the device has an unmounted child, select the child as mountable
        device otherwise select current device.

        :param volumeid: The volume to search
        :type volumeid: string

        :raises Exception: If none mountable devices can be found
        """
        lsblk_process = Popen(["lsblk", "--json", "--output",
                               "NAME,SERIAL,MOUNTPOINT"], stdout=PIPE)
        result = lsblk_process.communicate()[0].decode('UTF-8').strip()
        devices = json.loads(result)
        blk_device = None
        volume_serial = volumeid.replace('-', '')
        for device in devices['blockdevices']:
            if device['serial'] == volume_serial:
                if 'children' in device:
                    for child in device['children']:
                        if child['mountpoint'] == None:
                            blk_device = "/dev/" + child['name']
                            break
                if blk_device == None:
                    blk_device = "/dev/" + device['name']
                break
        if blk_device == None:
            raise Exception
        self.device = blk_device

    def mount_volume(self, volumeid):
        """
        Mount given volume to FS

        :param volumeid: Volume to be mounted
        :type volumeid: string
        """
        self.__wait_for_device_settle()
        try:
            self.__update_device_name(volumeid)
        except Exception as e:
            print(f"Unable to find device to mount.", file=sys.stderr)
            raise e
        if self.verbose > 1:
            print(f"Mounting '{self.device}' at '{self.mount_point}'")
        subprocess.call(["mount", "--source", self.device, "--target",
                         self.mount_point])

    def unmount_volume(self):
        """
        Umount devices from mount_point
        """
        if self.verbose > 1:
            print(f"Unmounting device at '{self.mount_point}'")
        subprocess.call(["umount", self.mount_point])

    def prepare_volume(self, volume_id, boot):
        """
        Partition fresh device

        1. Create a DOS partition table
        2. Create a primary partition and mark it as bootable (if selected)

        **NOTE:** Call this function before mounting a blank disk

        :param volume_id: Volume to be prepared
        :type volume_id: string
        :param boot: Make the primary partition bootable
        :type boot: boolean
        """
        self.__wait_for_device_settle()
        if boot:
            bootable = ", bootable"
        else:
            bootable = ""
        self.__update_device_name(volume_id)
        if self.verbose > 2:
            print(f"Partitioning device {self.device}")
        disk_process = Popen(["sfdisk", self.device], stdin=PIPE)
        disk_process.communicate(input=str.encode("label: dos\ntype=83" + bootable + "\n"))
        self.__wait_for_device_settle()
        self.__update_device_name(volume_id)
        if self.verbose > 2:
            print(f"Formating device {self.device} with ext4")
        subprocess.call(["mke2fs", "-t", "ext4", self.device])

    def untar(self, tar_location):
        """
        Start untar process

        1. Create untar process if it does not exists.
        2. Pipe the tar file to stdin of untar process
        3. Remove the tar file

        :param tar_location: Location of the tar file
        :type tar_location: string
        """
        print(f"Untaring file '{tar_location}' to '{self.mount_point}'")
        if self.untar_process == None:
            tar_options = ["tar", "--extract", "--directory", self.mount_point,
                           "--preserve-permissions", "--preserve-order"]
            if ".tar.gz" in tar_location:
                tar_options.append("--gzip")
            self.untar_process = Popen(tar_options, stdin=PIPE)
        temp_file_obj = open(tar_location, "rb")
        temp_file_obj.seek(0, os.SEEK_END)
        file_length = temp_file_obj.tell()
        temp_file_obj.seek(0, os.SEEK_SET)
        free_mem = psutil.virtual_memory().available
        max_chunk = free_mem - self.TEN_MB
        while temp_file_obj.tell() < file_length:
            self.untar_process.stdin.write(temp_file_obj.read(max_chunk))
        temp_file_obj.close()
        os.unlink(tar_location)

    def terminate_tar(self):
        """
        Close the untar process
        """
        self.untar_process.stdin.close()
        self.untar_process.wait()

    def mount_required_folders(self):
        """
        Mount the required folders for chroot
        """
        for loc in ["/sys", "/proc", "/run", "/dev"]:
            subprocess.call(["mount", "--bind", loc, self.mount_point + loc])

    def unmount_required_folders(self):
        """
        Unmount the required folders for chroot
        """
        for loc in ["/sys", "/proc", "/run", "/dev"]:
            subprocess.call(["umount", self.mount_point + loc])

    def update_grub(self, volumeid):
        """
        Update the grub settings for the disk

        Chroot to the freshly tared location and update the grub.

        :param volumeid: The volume to search
        :type volumeid: string
        """
        print(f"ChRooting to {self.mount_point} to fix grub")
        mbr_device = self.__get_mbr_device_name(volumeid)
        real_root = os.open("/", os.O_RDONLY)
        current_dir = os.getcwd()
        os.chdir(self.mount_point)
        os.chroot(self.mount_point)
        subprocess.call(["grub-install", mbr_device])
        subprocess.call(["update-grub"])
        os.fchdir(real_root)
        os.chroot(".")
        os.chdir(current_dir)
        os.close(real_root)

    def update_fstab(self):
        """
        Update the fstab/disk

        Update the LABEL of volume or UUID in fstab
        """
        with open(f"{self.mount_point}/etc/fstab", "r") as fstab_file:
            fstab = fstab_file.readline()
        fstab_pattern = r"((?:UUID)|(?:LABEL))=([0-9a-z\-]+)\s+((?:\/boot)|(?:\/))\s+(ext(?:[2-4]))"
        results = re.findall(fstab_pattern, fstab, re.RegexFlag.IGNORECASE)
        if len(results) < 1:
            raise Exception("Unable to understand fstab")
        if results[0][0].lower() == "uuid":
            if self.verbose > 1:
                print("The old snapshot was mounted using UUID=" +
                      results[0][1])
            blkid_process = Popen(["blkid", "--output", "export", self.device],
                                  stdout=PIPE)
            blkid_response = blkid_process.communicate()[0].decode('UTF-8').strip()
            blkid_pattern = r"^UUID=([0-9a-z\-]+)$"
            blkid_uuid = re.findall(blkid_pattern, blkid_response,
                                    re.RegexFlag.IGNORECASE | re.RegexFlag.MULTILINE)[0]
            if self.verbose > 1:
                print("New UUID of volume=" + blkid_uuid)
            new_fstab = fstab.replace(results[0][1], blkid_uuid)
            with open(f"{self.mount_point}/etc/fstab", "w") as fstab_file:
                fstab_file.write(new_fstab)
        elif results[0][0].lower() == "label":
            label = results[0][1]
            if self.verbose > 1:
                print(f"The old snapshot was mounted using LABEL={label}")
            subprocess.call(["e2label", self.device, label])
            time.sleep(1)
            e2label_process = Popen(["e2label", self.device], stdout=PIPE)
            response = e2label_process.communicate()[0].decode('UTF-8').strip()
            if response != label:
                raise Exception("Unable to change the volume label to " +
                                f"'{label}'")
            if self.verbose > 1:
                print(f"Updated new volume with LABEL={label}")
        else:
            raise Exception("Unable to understand fstab")

    def get_mounted_disc_size(self):
        """
        Get the size of mounted partition

        Uses ``df`` to get the size of partition. This makes it less accurate
        but faster than using ``du``.

        :return: Size of the mounted partition in bytes
        :rtype: int
        """
        df_process = Popen(["/bin/df", "--sync", "-k", "--local",
                            "--output=used", self.mount_point], stdout=PIPE)
        return int(
            (df_process.communicate()[0].decode('UTF-8').strip().split('\n'))[1]) * 1024
