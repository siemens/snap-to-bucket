#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = "Siemens AG"

import gc
import os
import sys
import time
import base64
import hashlib
import threading
from datetime import datetime
from subprocess import PIPE, Popen

import boto3
import psutil
from botocore.exceptions import ClientError


class ProgressPercentage:
    """
    Progress percentage printer
    """

    def __init__(self, filename, size):
        self._filename = filename
        self._size = size
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount):
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = round((self._seen_so_far / self._size) * 100, 2)
            sys.stdout.write(f"Downloading {self._filename}: {percentage}% " +
                             "done \r")
            sys.stdout.flush()


class S3Handler:
    """
    Class to handle communications with S3 services

    :ivar s3client: S3 client from boto3
    :ivar bucket: Name of the bucket to use
    :ivar verbose: Verbosity level (0-3)
    :ivar temp_download: Path of the location where object from S3 is stored
    :ivar restore_partition_size: Size of partition being restored
    :ivar split_size: Size in bytes to split tar at
    :ivar gzip: True to compress tar with gzip
    :ivar storage_class: Storage class of S3 object
    :ivar FIVE_HUNDRED_MB: Five hundred MiB in bytes
    :ivar FIVE_GB: Five GiB in bytes
    """

    FIVE_HUNDRED_MB = 500 * (1024 ** 2)
    FIVE_GB = (5 * (1024 ** 3))

    def __init__(self, bucket, split_size=5497558138880.0, gzip=False,
                 storage_class="STANDARD", verbose=0):
        """
        Initializer for the class attributes.

        Additionally, check if the provided bucket can be accessed.

        :param bucket: Bucket to use
        :type bucket: string
        :param split_size: Split size of tar
        :type split_size: float
        :param gzip: True to compress tar with gzip
        :type gzip: boolean
        :param storage_class: Storage class of S3 object
        :type storage_class: string
        :param verbose: Verbosity level (0-3)
        :type verbose: integer
        """
        self.s3client = boto3.client("s3")
        self.bucket = bucket
        self.__check_bucket_accessiblity(bucket)
        self.split_size = split_size
        self.gzip = gzip
        self.storage_class = storage_class
        self.verbose = verbose
        self.temp_download = None
        self.restore_partition_size = 0

    def __check_bucket_accessiblity(self, bucket):
        """
        Check if the bucket can be accessed

        :param bucket: Bucket to check
        :type bucket: string

        :raises Exception: If the bucket can't be accessed
        """
        try:
            response = self.s3client.head_bucket(Bucket=bucket)
            if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
                raise Exception
        except Exception as ex:
            print(f"Unable to access bucket '{bucket}'", file=sys.stderr)
            raise ex

    def __get_object_count(self, key):
        """
        Get the count of objects under given key

        This function also assigns value to attribute ``restore_partition_size``.
        If the object has meta data ``x-amz-meta-disc-size`` and value if
        greater than 1, partition size is assigned to its value.
        Otherwise, partition size is assigned value of content length

        :param key: Object key to check
        :type key: string

        :return: Number of objects with ``key`` as the prefix
        :rtype: integer

        :raises Exception: If the objects can't be accessed
        """
        try:
            response = self.s3client.list_objects_v2(Bucket=self.bucket,
                                                    Prefix=key)
            if response["ResponseMetadata"]["HTTPStatusCode"] != 200 or "Contents" not in response:
                raise Exception
            objects = list(response["Contents"])
            response = self.s3client.head_object(Bucket=self.bucket,
                                                 Key=objects[0]["Key"])
            partition_size = 0
            if "x-amz-meta-disc-size" in response["Metadata"]:
                partition_size = int(
                    response["Metadata"]["x-amz-meta-disc-size"])
            if partition_size < 2:
                partition_size = sum([int(o["Size"]) for o in objects])
            self.restore_partition_size = partition_size
            return len(objects)
        except Exception as ex:
            print(f"Unable to access key '{key}' in bucket '{self.bucket}'",
                  file=sys.stderr)
            raise ex

    @staticmethod
    def byte_checksum(data):
        """
        Calculate the checksum for the given bytes

        :param data: Data to calculate checksum for
        :type data: byte

        :return: The Base64 encoded MD5 checksum
        :rtype: string
        """
        md_obj = hashlib.md5()
        md_obj.update(data)
        return base64.b64encode(md_obj.digest()).decode("UTF-8").strip()

    def __get_key_uploadid(self, snapshot, size, partno):
        """
        Generate the key and uploadid for a snapshot

        :param snapshot: Snapshot to get the key for
        :type snapshot: dict()
        :param size: Size of mounted partition
        :type size: integer
        :param partno: Part no of the upload (-1 for single part upload)
        :type partno: integer

        :return: S3 key and uploadid for the snapshot
        :rtype: list()
        """
        meta_data = {}
        content_type = "application/x-tar"
        timestr = datetime.now().isoformat(timespec="seconds")
        created = snapshot["created"].isoformat(timespec="seconds")
        name = snapshot["name"].replace(" ", "+").replace("/", "_")
        key = f"snap/{name}/{snapshot['id']}-{created}-{timestr}"
        meta_data["creation-time"] = snapshot["created"].isoformat()
        meta_data["snap-volume-size"] = f"{snapshot['volumesize']} GiB"
        if partno == -1:
            key = f"{key}.tar"
            if self.gzip:
                key = f"{key}.gz"
                content_type = "application/gzip"
        else:
            key = f"{key}-part{partno}.tar"
            if self.gzip:
                key = f"{key}.gz"
                content_type = "application/gzip"
        if size > 1:
            meta_data["x-amz-meta-disc-size"] = str(size)
        res = self.s3client.create_multipart_upload(
            Bucket=self.bucket,
            ContentType=content_type,
            Key=key,
            Metadata=meta_data,
            StorageClass=self.storage_class
        )
        return (key, res["UploadId"])

    def initiate_upload(self, snapshot, path, size=0):
        """
        Start multipart upload

        1. Initialize the variables
            1. If the upload can be done in one go, set partno as -1
        2. Get the first key and upload id
        3. Create a tar process
        4. Read a chunk (max 5 GB or available RAM size - 50 MB of overhead or
        remaining size before split occurs)
            1. Have read enough data for split
                1. Finish the upload, reset the counters
                2. If more data to read, get new key and upload id.
                3. Otherwise break.
            2. Calculate new chunk size to be read
            3. Read the chunk, update the counters and get the checksum of the
                chunk
            4. Upload part and add returned Etag to list
        4. Finish the upload

        If upload fails in between, abort the upload

        :param snapshot: Snapshot to be uploaded
        :type snapshot: dict()
        :param path: Path of the mounted directory
        :type path: string
        :param size: Size of the partition (attached as meta info)
        :type size: integer
        """
        uploaded_bytes = 0
        if self.split_size >= size:
            if self.verbose > 1:
                print("Uploading snapshot as a single file as " +
                      f"{self.split_size} >= {size}")
            partno = -1
        else:
            partno = 1
        tar_process = Popen(["tar", "--directory", path, "--create",
                             "--preserve-permissions", "."], stdout=PIPE)
        read_process = tar_process
        if self.gzip:
            gzip_process = Popen(["gzip", "--to-stdout", "-6"],
                                 stdin=tar_process.stdout, stdout=PIPE)
            read_process = gzip_process
        more_to_read = True
        try:
            while more_to_read:
                (key, uploadid) = self.__get_key_uploadid(snapshot, size,
                                                          partno)
                (uploaded_bytes, more_to_read) = self.__read_and_upload_part(
                    read_process, uploaded_bytes, key, uploadid)
                partno += 1
        finally:
            read_process = None
            if self.gzip:
                gzip_process.wait()
            tar_process.wait()
        print()
        if self.verbose > 0:
            print("Multipart upload finished. Sending complete")

    def __read_and_upload_part(self, read_process, uploaded_bytes, key,
                               upload_id):
        """
        Prepare an upload a single part of the tar.

        1. Read the data from read_process
        2. Upload it as multipart upload
        3. Check if there is more data to be uploaded
        4. Set the flag and complete the multipart upload

        :param read_process: The process to read from
        :type read_process: subprocess.Popen
        :param uploaded_bytes: No of bytes already uploaded
        :type uploaded_bytes: integer
        :param key: S3 key
        :type key: string
        :param upload_id: S3 multipart upload id
        :type upload_id: string

        :return: No of total bytes uploaded, is there more data to process
        :rtype: dict(integer, boolean)
        """
        tar_read_bytes = 0
        upload_partid = 1
        parts_info = []
        more_to_read = True
        print(f"Uploading {key} to {self.bucket} bucket")
        while True:
            free_mem = psutil.virtual_memory().available
            if free_mem > self.FIVE_GB: # Maximum part size is 5 GiB
                free_mem = self.FIVE_GB
            max_chunk = free_mem - self.FIVE_HUNDRED_MB
            if tar_read_bytes + max_chunk > self.split_size:
                read_chunk = self.split_size - tar_read_bytes
            else:
                read_chunk = max_chunk
            try:
                inline = read_process.stdout.read(read_chunk)
                if len(inline) == 0:
                    # No more data to read
                    more_to_read = False
                    break
                tar_read_bytes += len(inline)
                uploaded_bytes += len(inline)
                resp = self.__upload_s3_part(inline, key, upload_partid,
                                             upload_id)
                del inline
                parts_info.append({
                    "ETag": resp["ETag"],
                    "PartNumber": upload_partid
                })
                if self.verbose > 0:
                    print(f"Part # {upload_partid}, ", end="")
                print("Uploaded " +
                      str(round(uploaded_bytes / (1024 ** 2), 2)) +
                      " MiB (total) ", end="\r")
                upload_partid += 1
                gc.collect()
                if tar_read_bytes >= self.split_size:
                    # One split upload completed
                    break
            except Exception as ex:
                print("\nMultipart upload failed. Trying to abort",
                      file=sys.stderr)
                inline = None # Safely drop the data
                self.s3client.abort_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id
                )
                raise ex
        self.__complete_upload(key, upload_id, parts_info)
        return uploaded_bytes, more_to_read

    def __upload_s3_part(self, body, key, part_id, upload_id, retry_count=0):
        """
        Upload a part of S3 multipart upload.

        The function also reties failed calls. Every upload request, if failed,
        will be retried 4 times at 4 seconds of intervals.

        :param body: Body of the upload
        :param key: S3 object key
        :type key: string
        :param part_id: Upload part ID
        :type part_id: int
        :param upload_id: Multipart upload's Upload ID
        :type upload_id: string
        :param retry_count: How many retries have been done.
        :type retry_count: int

        :return: Response from S3

        :raises Exception: If all upload attempt fails
        """
        if retry_count > 3:
            raise Exception("S3 multipart part upload failed")
        try:
            return self.s3client.upload_part(
                Body=body,
                Bucket=self.bucket,
                ContentMD5=S3Handler.byte_checksum(body),
                Key=key,
                PartNumber=part_id,
                UploadId=upload_id
            )
        except ClientError as error:
            print(f"Failed: '{error.response['Error']['Message']}'.\nRetrying.",
                  file=sys.stderr)
            time.sleep(4.0)
            return self.__upload_s3_part(body, key, part_id, upload_id,
                                         retry_count + 1)

    def __complete_upload(self, key, uploadid, partlist, retry_count=0):
        """
        Complete a multipart upload

        The function also reties failed calls. Every upload request, if failed,
        will be retried 4 times at 4 seconds of intervals.

        :param key: Key of the upload
        :type key: string
        :param uploadid: Upload id of the multipart upload
        :type uploadid: string
        :param partlist: List of uploaded parts
        :type partlist: list(dict())

        :raises Exception: If all upload attempt fails, abort uploads.
        """
        if retry_count > 3:
            print("\nMultipart upload failed. Trying to abort",
                  file=sys.stderr)
            self.s3client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=uploadid
            )
            raise Exception("S3 upload failed")
        try:
            self.s3client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                MultipartUpload={
                    "Parts": partlist
                },
                UploadId=uploadid
            )
        except ClientError as error:
            print(f"Failed: '{error.response['Error']['Message']}'.\nRetrying.",
                  file=sys.stderr)
            time.sleep(4.0)
            self.__complete_upload(key, uploadid, partlist, retry_count + 1)
        if self.verbose > 0:
            print(f"\nCompleted multipart upload, key: {key}")

    def get_object_count_and_size(self, key):
        """
        Check if the given key is available and return number of objects under
        it.

        :param key: Key to check
        :type key: string

        :return: Number of objects under provided key prefix, size of unpacked
            tar
        :rtype: tuple(integer, integer)
        """
        return (self.__get_object_count(key),
                self.restore_partition_size)

    def download_key(self, key, partno, restore_dir):
        """
        Download the key from S3

        Create a temporary path to download the key and start download.

        :param key: Key to be downloaded
        :type key: string
        :param partno: Part number of the key to be downloaded (-1 if there is
            only one part)
        :type partno: integer
        :param restore_dir: Location to store S3 object for restore
        :type restore_dir: string

        :return: Location of downloaded file and size of restored partition (in
            bytes)
        :rtype: dict(string, integer)

        :raises Exception: If download fails, delete the temp location
        """
        response = self.s3client.list_objects_v2(Bucket=self.bucket,
                                                 Prefix=key)
        keys = [o["Key"] for o in response["Contents"]]
        download_key_name = None
        if partno == -1:
            download_key_name = keys[0]
        else:
            for dkey in keys:
                if f"-part{partno}.tar" in dkey:
                    download_key_name = dkey
                    break
        if download_key_name is None:
            raise Exception(f"Unable to find part '{partno}' under key {key}")
        self.temp_download = os.path.join(restore_dir, download_key_name)
        os.makedirs(os.path.dirname(self.temp_download), exist_ok=True)
        size = self.s3client.head_object(Bucket=self.bucket,
                                         Key=download_key_name)["ContentLength"]
        progress = ProgressPercentage(key, size)
        try:
            self.s3client.download_file(self.bucket, download_key_name,
                                        self.temp_download, Callback=progress)
            print()
        except Exception as ex:
            print(f"Failed while downloading s3://{self.bucket}/{download_key_name}",
                  file=sys.stderr)
            os.remove(self.temp_download)
            raise ex
        return self.temp_download
