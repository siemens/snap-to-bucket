#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = 'Siemens AG'

import gc
import os
import sys
import base64
import hashlib
import threading
from datetime import datetime
from subprocess import PIPE, Popen

import boto3
import psutil


class ProgressPercentage(object):
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
    """

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
        self.s3client = boto3.client('s3')
        self.bucket = bucket
        self.__check_bucket_accessiblity(bucket)
        self.split_size = split_size
        self.gzip = gzip
        self.storage_class = storage_class
        self.verbose = verbose

    def __check_bucket_accessiblity(self, bucket):
        """
        Check if the bucket can be accessed

        :param bucket: Bucket to check
        :type bucket: string

        :raises Exception: If the bucket can't be accessed
        """
        try:
            response = self.s3client.head_bucket(Bucket=bucket)
            if response['ResponseMetadata']['HTTPStatusCode'] != 200:
                raise Exception
        except Exception as e:
            print(f"Unable to access bucket '{bucket}'", file=sys.stderr)
            raise e

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
            if response['ResponseMetadata']['HTTPStatusCode'] != 200 or 'Contents' not in response:
                raise Exception
            objects = [o for o in response['Contents']]
            response = self.s3client.head_object(Bucket=self.bucket,
                                                 Key=objects[0]['Key'])
            partition_size = 0
            if 'x-amz-meta-disc-size' in response['Metadata']:
                partition_size = int(
                    response['Metadata']['x-amz-meta-disc-size'])
            if partition_size < 2:
                partition_size = sum([int(o['Size']) for o in objects])
            self.restore_partition_size = partition_size
            return len(objects)
        except Exception as e:
            print(f"Unable to access key '{key}' in bucket '{self.bucket}'",
                  file=sys.stderr)
            raise e

    def __byte_checksum(self, data):
        """
        Calculate the checksum for the given bytes

        :param data: Data to calculate checksum for
        :type data: byte

        :return: The Base64 encoded MD5 checksum
        :rtype: string
        """
        md_obj = hashlib.md5()
        md_obj.update(data)
        return base64.b64encode(md_obj.digest()).decode('UTF-8').strip()

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
        meta_data = dict()
        content_type = 'application/x-tar'
        timestr = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        name = snapshot['name'].replace(' ', '+').replace('/', '_')
        key = f"snap/{name}/{snapshot['id']}-{timestr}"
        if partno == -1:
            key = f"{key}.tar"
            if self.gzip:
                key = f"{key}.gz"
                content_type = 'application/gzip'
        else:
            key = f"{key}-part{partno}.tar"
            if self.gzip:
                key = f"{key}.gz"
                content_type = 'application/gzip'
        if size > 1:
            meta_data["x-amz-meta-disc-size"] = str(size)
        res = self.s3client.create_multipart_upload(
            Bucket=self.bucket,
            ContentType=content_type,
            Key=key,
            Metadata=meta_data,
            StorageClass=self.storage_class
        )
        return (key, res['UploadId'])

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
        tar_read_bytes = 0
        fifty_mb = 50 * (1024 ** 2)
        five_gb = (5 * (1024 ** 3))
        free_mem = psutil.virtual_memory().available
        if free_mem > five_gb:
            free_mem = five_gb
        max_chunk = free_mem - fifty_mb
        if self.split_size >= size:
            if self.verbose > 1:
                print("Uploading snapshot as a single file as " +
                      f"{self.split_size} >= {size}")
            partno = -1
        else:
            partno = 1
        (key, uploadid) = self.__get_key_uploadid(snapshot, size, partno)
        tar_process = Popen(["tar", "--directory", path, "--create",
                             "--preserve-permissions", "."], stdout=PIPE)
        read_process = tar_process
        if self.gzip:
            gzip_process = Popen(["gzip", "--to-stdout", "-6"],
                                 stdin=tar_process.stdout, stdout=PIPE)
            read_process = gzip_process
        upload_partid = 1
        parts_info = list()
        print(f"Uploading {key} to {self.bucket} bucket")
        while True:
            if (tar_read_bytes >= self.split_size):
                self.__complete_upload(key, uploadid, parts_info)
                partno += 1
                parts_info = list()
                upload_partid = 1
                tar_read_bytes = 0
                if len(read_process.stdout.peek()) != 0:
                    (key, uploadid) = self.__get_key_uploadid(snapshot, size,
                                                              partno)
                else:
                    break
            if tar_read_bytes + max_chunk > self.split_size:
                read_chunk = self.split_size - tar_read_bytes
            else:
                read_chunk = max_chunk
            try:
                inline = read_process.stdout.read(read_chunk)
                if len(inline) == 0:
                    self.__complete_upload(key, uploadid, parts_info)
                    break
                tar_read_bytes += len(inline)
                uploaded_bytes += len(inline)
                resp = self.s3client.upload_part(
                    Body=inline,
                    Bucket=self.bucket,
                    ContentLength=len(inline),
                    ContentMD5=self.__byte_checksum(inline),
                    Key=key,
                    PartNumber=upload_partid,
                    UploadId=uploadid
                )
                inline = None
                parts_info.append({
                    'ETag': resp['ETag'],
                    'PartNumber': upload_partid
                })
                if self.verbose > 0:
                    print(f"Part # {upload_partid}, ", end='')
                print("Uploaded " +
                      str(round(uploaded_bytes / (1024 ** 2), 2)) +
                      " Mb (total) ", end="\r")
                upload_partid += 1
                gc.collect()
            except Exception as e:
                print("\nMultipart upload failed. Trying to abort",
                      file=sys.stderr)
                self.s3client.abort_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=uploadid
                )
                raise e
        read_process = None
        if self.gzip:
            gzip_process.wait()
        tar_process.wait()
        print()
        if self.verbose > 0:
            print("Multipart upload finished. Sending complete")

    def __complete_upload(self, key, uploadid, partlist):
        """
        Complete a multipart upload

        :param key: Key of the upload
        :type key: string
        :param uploadid: Upload id of the multipart upload
        :type uploadid: string
        :param partlist: List of uploaded parts
        :type partlist: list(dict())
        """
        self.s3client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            MultipartUpload={
                'Parts': partlist
            },
            UploadId=uploadid
        )
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
        keys = [o['Key'] for o in response['Contents']]
        download_key_name = None
        if partno == -1:
            download_key_name = keys[0]
        else:
            for key in keys:
                if f"-part{partno}.tar" in key:
                    download_key_name = key
                    break
        if download_key_name == None:
            raise Exception(f"Unable to part '{partno}' under key {key}")
        self.temp_download = os.path.join(restore_dir, download_key_name)
        size = self.s3client.head_object(Bucket=self.bucket,
                                         Key=download_key_name)['ContentLength']
        progress = ProgressPercentage(key, size)
        try:
            self.s3client.download_file(self.bucket, download_key_name,
                                        self.temp_download, Callback=progress)
            print()
        except Exception as e:
            print(f"Failed while downloading s3://{self.bucket}/{download_key_name}",
                  file=sys.stderr)
            os.remove(self.temp_download)
            raise e
        return self.temp_download
