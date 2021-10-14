#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = "Siemens AG"

import os
import sys
import json
import math
import urllib.request
from datetime import datetime

import boto3


class Ec2Handler:
    """
    Class to handle communications with EC2 services

    :ivar tag: Name of the tag to search in snapshots
    :ivar volume_type: The volume type to create from snapshot
    :ivar verbose: Verbosity level (0-3)
    :ivar instance_info: Current instance info by 169.254.169.254
    :ivar ec2client: EC2 client from boto3
    :ivar iops: IOPS for supported volumes
    :ivar throughput: Throughput for supported volumes
    """

    def __init__(self, tag="snap-to-bucket", volume_type="gp2", verbose=0,
                 iops=None, throughput=None):
        """
        Initializer for the class attributes.

        Additionally, fetches the current instance information from
        169.254.169.254 and set the default region as per current instance
        region.

        :param tag: Tag for snapshots
        :type tag: str
        :param volume_type: Volume type on EC2
        :type volume_type: str
        :param verbose: Verbosity level (0-3)
        :type verbose: int
        :param iops: IOPS for supported volumes
        :type iops: int
        :param throughput: Throughput for supported volumes
        :type throughput: int
        """
        self.tag = tag
        self.volume_type = volume_type
        self.verbose = verbose
        self.iops = iops
        self.throughput = throughput
        try:
            response = urllib.request.urlopen(
                "http://169.254.169.254/latest/dynamic/instance-identity/document/")
        except urllib.error.URLError as ex:
            print("Script needs to run on an EC2 instance", file=sys.stderr)
            raise ex
        self.instance_info = json.loads(response.read().decode("UTF-8").strip())
        response.close()
        if self.verbose > 0:
            print("Current instance is '" + self.instance_info["instanceId"] +
                  "'")
        os.environ["AWS_DEFAULT_REGION"] = self.instance_info["region"]
        self.ec2client = boto3.client("ec2")

    def get_snapshots(self):
        """
        Get the list of snapshots which are to be migrated.

        The function checks all snapshots with tag stored holding value migrate.

        :return: List of snapshots dictionaries with id and name
        :rtype: list()
        """
        responses = []
        responses.append(self.ec2client.describe_snapshots(
            Filters=[
                {
                    "Name": "tag:" + self.tag,
                    "Values": [
                        "migrate"
                    ]
                }
            ]
        ))
        while responses[-1].get("NextToken", None) is not None:
            responses.append(self.ec2client.describe_snapshots(
                Filters=[
                    {
                        "Name": "tag:" + self.tag,
                        "Values": [
                            "migrate"
                        ]
                    }
                ],
                NextToken=responses[-1]["NextToken"]
            ))
        snapshots = []
        for response in responses:
            for snap in response["Snapshots"]:
                snapshot = {}
                snapshot["id"] = snap["SnapshotId"]
                snapshot["created"] = snap["StartTime"]
                snapshot["volumesize"] = snap["VolumeSize"]
                for tag in snap["Tags"]:
                    if tag["Key"].lower() == "name":
                        snapshot["name"] = tag["Value"]
                        break
                snapshots.append(snapshot)
        if self.verbose > 0:
            print("Found " + str(len(snapshots)) + " snapshots")
        return snapshots

    def create_volume(self, snapshot):
        """
        Create a new volume based on snapshot

        Creates a new volume from the given snapshot and wait till the volume
        get ready.
        Also set the tag of volume to created and add name as
        'snap-to-bucket-' + id

        :param snapshot: Snapshot info holding id and name keys
        :type snapshot: dict()

        :return: ID of newly created volume
        :rtype: str
        :raises botocore.exceptions.WaiterError: If the volume creation failed,
            try to delete it and raise exception
        """
        arguments = {
            "AvailabilityZone": self.instance_info["availabilityZone"],
            "Encrypted": False,
            "SnapshotId": snapshot["id"],
            "VolumeType": self.volume_type
        }
        if self.iops is not None:
            arguments["Iops"] = self.iops
        if self.throughput is not None:
            arguments["Throughput"] = self.throughput
        volumeid = self.ec2client.create_volume(
            **arguments,
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": [
                    {
                        "Key": self.tag,
                        "Value": "created"
                    },
                    {
                        "Key": "Name",
                        "Value": "snap-to-bucket-" + snapshot["id"]
                    }
                ]
            }]
        )["VolumeId"]
        if self.verbose > 1:
            print(f"Created '{volumeid}' volume")
        try:
            if self.__volume_is_ready(volumeid):
                if self.verbose > 2:
                    print(f"Volume '{volumeid}' is ready")
                return volumeid
        except Exception as ex:
            print(f"Timed out while waiting for '{volumeid}' to get ready",
                  file=sys.stderr)
            print("Attempting to delete the volume", file=sys.stderr)
            self.delete_volume(volumeid)
            raise ex
        return None

    def create_empty_volume(self, size):
        """
        Create a new empty volume without snapshot

        Creates a new volume and wait till the volume get ready.
        The volume size if increased by 25% before creating it.
        Also set the tag of volume to created and add name as
        ``snap-to-bucket-%Y-%m-%d_%H-%M-%S-%f``

        :param size: Size of the volume in bytes
        :type size: int

        :return: ID of newly created volume
        :rtype: str
        :raises botocore.exceptions.WaiterError: If the volume creation failed,
            try to delete it and raise exception
        """
        vol_size = math.ceil(size / (1024 ** 3)) * (1.25)
        vol_size = max(vol_size, 1)
        timestr = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        arguments = {
            "AvailabilityZone": self.instance_info["availabilityZone"],
            "Encrypted": False,
            "Size": round(vol_size),
            "VolumeType": self.volume_type
        }
        if self.iops is not None:
            arguments["Iops"] = self.iops
        if self.throughput is not None:
            arguments["Throughput"] = self.throughput
        volumeid = self.ec2client.create_volume(
            **arguments,
            TagSpecifications=[{
                "ResourceType": "volume",
                "Tags": [
                    {
                        "Key": self.tag,
                        "Value": "restore-volume"
                    },
                    {
                        "Key": "Name",
                        "Value": f"snap-to-bucket-{timestr}"
                    }
                ]
            }]
        )["VolumeId"]
        if self.verbose > 1:
            print(f"Created '{volumeid}' volume")
        try:
            if self.__volume_is_ready(volumeid):
                if self.verbose > 2:
                    print(f"Volume '{volumeid}' is ready")
                return volumeid
        except Exception as ex:
            print(f"Timed out while waiting for '{volumeid}' to get ready",
                  file=sys.stderr)
            print("Attempting to delete the volume", file=sys.stderr)
            self.delete_volume(volumeid)
            raise ex
        return None

    def __volume_is_ready(self, volumeid):
        """
        Wait till volume is ready

        :param volumeid: Volume id to wait for
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume creation failed
        """
        self.ec2client.get_waiter("volume_available").wait(
            VolumeIds=[volumeid],
            WaiterConfig={
                "Delay": 10,
                "MaxAttempts": 50
            }
        )
        return True

    def __volume_is_attached(self, volumeid):
        """
        Wait till volume is attached to instance

        :param volumeid: Volume id to wait for
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume attachment failed
        """
        self.ec2client.get_waiter("volume_in_use").wait(
            VolumeIds=[volumeid]
        )
        return True

    def __volume_is_deleted(self, volumeid):
        """
        Wait till volume is deleted

        :param volumeid: Volume id to wait for
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume deletion failed
        """
        self.ec2client.get_waiter("volume_deleted").wait(
            VolumeIds=[volumeid]
        )
        return True

    def attach_volume(self, volumeid):
        """
        Attach given volume to current instance

        :param volumeid: Volume id to attach
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume attachment failed,
            try to delete it and raise exception
        """
        try:
            self.ec2client.attach_volume(
                Device="/dev/sdk",
                InstanceId=self.instance_info["instanceId"],
                VolumeId=volumeid
            )
        except Exception as ex:
            print(f"Failed to attach volume '{volumeid}' to instance '" +
                  self.instance_info["instanceId"] + "'", file=sys.stderr)
            print(f"Deleting volume '{volumeid}'", file=sys.stderr)
            self.delete_volume(volumeid)
            raise ex
        if self.verbose > 1:
            print(f"Attaching volume '{volumeid}' to instance '" +
                  self.instance_info["instanceId"] + "'")
        if self.__volume_is_attached(volumeid):
            if self.verbose > 2:
                print(f"Volume '{volumeid}' attached to '" +
                      self.instance_info["instanceId"] + "'")
            return True
        return False

    def detach_volume(self, volumeid):
        """
        Detach given volume from current instance

        :param volumeid: Volume id to detach
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume detachment failed
        """
        try:
            self.ec2client.detach_volume(
                Force=True,
                VolumeId=volumeid
            )
        except Exception as ex:
            print(f"Unable to detach volume '{volumeid}' from instance '" +
                  self.instance_info["instanceId"] + "'", file=sys.stderr)
            raise ex
        if self.verbose > 1:
            print(f"Detaching volume '{volumeid}' from instance '" +
                  self.instance_info["instanceId"] + "'")
        if self.__volume_is_ready(volumeid):
            if self.verbose > 2:
                print(f"Volume '{volumeid}' detached from '" +
                      self.instance_info["instanceId"] + "'")
            return True
        return False

    def delete_volume(self, volumeid):
        """
        Deletes a volume

        :param volumeid: Volume id to be deleted
        :type volumeid: str

        :raises botocore.exceptions.WaiterError: If the volume deletion failed
        """
        self.ec2client.delete_volume(
            VolumeId=volumeid
        )
        if self.verbose > 1:
            print(f"Deleting volume '{volumeid}'")
        if self.__volume_is_deleted(volumeid):
            if self.verbose > 2:
                print(f"Volume '{volumeid}' deleted")
            return True
        return False

    def delete_snapshot(self, snapshot):
        """
        Deletes a snapshot

        :param snapshot: Snapshot to be deleted
        :type snapshot: dict()
        """
        self.ec2client.delete_snapshot(
            SnapshotId=snapshot["id"]
        )
        print(f"Deleting snapshot '{snapshot['id']}'")

    def update_snapshot_tag(self, snapshot):
        """
        Update snapshot tag to transferred

        :param snapshot: Snapshot to be updated
        :type snapshot: dict()
        """
        self.ec2client.create_tags(
            Resources=[
                snapshot["id"]
            ],
            Tags=[
                {
                    "Key": self.tag,
                    "Value": "transferred",
                }
            ]
        )
        if self.verbose > 0:
            print(f"Updated tag for snapshot '{snapshot['id']}'")
