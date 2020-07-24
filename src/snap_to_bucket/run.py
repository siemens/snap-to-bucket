#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SPDX-FileCopyrightText: Siemens AG, 2020 Gaurav Mishra <mishra.gaurav@siemens.com>

SPDX-License-Identifier: MIT
"""
__author__ = 'Siemens AG'

import os
import re
import math
import argparse

from snap_to_bucket import SnapToBucket


def main(args):
    """
    The real magic starts here
    """
    snap_to_bucket = SnapToBucket(args.bucket, args.tag, args.verbose,
                                  args.type, args.storage_class, args.mount,
                                  args.delete, args.restore, args.key,
                                  args.boot, args.restore_dir)
    snap_to_bucket.update_proxy(args.proxy, args.noproxy)
    snap_to_bucket.update_split_size(args.split)
    if args.gzip:
        snap_to_bucket.perform_gzip()
    snap_to_bucket.initiate_migration()


def split_size(arg):
    """
    Function to parse the split argument

    :param arg: Argument from user
    :type arg: string

    :return: parsed size in bytes
    :rtype: integer
    """
    match_result = re.match(r"^([\d\.]+)(b|k|m|g|t)$", arg,
                            re.RegexFlag.IGNORECASE | re.RegexFlag.MULTILINE)
    if match_result:
        value = match_result.group(1)
        spit_bytes = 0
        if match_result.group(2) == "b":
            spit_bytes = float(value)
        elif match_result.group(2) == "k":
            spit_bytes = float(value) * 1024.0
        elif match_result.group(2) == "m":
            spit_bytes = float(value) * 1024.0 * 1024.0
        elif match_result.group(2) == "g":
            spit_bytes = float(value) * 1024.0 * 1024.0 * 1024.0
        elif match_result.group(2) == "t":
            spit_bytes = float(value) * 1024.0 * 1024.0 * 1024.0 * 1024.0
        if spit_bytes > 5497558138880.0:
            raise argparse.ArgumentTypeError("Can not have spit size greater " +
                                             "than 5t")
        if spit_bytes < 5242880.0:
            raise argparse.ArgumentTypeError("Can not have spit size lesser " +
                                             "than 5m")
        return int(math.ceil(spit_bytes))
    else:
        raise argparse.ArgumentTypeError(f"{arg} not in <size><b|k|m|g|t> format")


def entrypoint():
    """
    Entrypoint for the main program
    """
    parser = argparse.ArgumentParser(description='''
    snap_to_bucket is a simple tool based on boto3 to move snapshots to S3
    buckets
    ''')
    parser.add_argument("-v", "--verbose", help="increase output verbosity " +
                        "(-vvv for more verbosity)", action="count", default=0)
    parser.add_argument("-b", "--bucket", help="S3 bucket to push snaps in",
                        required=True)
    parser.add_argument("--proxy", help="proxy to be used", default=None,
                        required=False)
    parser.add_argument("--noproxy", help="comma separated list of domains " +
                        "which do not require proxy", default=None,
                        required=False)
    parser.add_argument("-t", "--tag", help="tag on snapshots " +
                        "(default: %(default)s)", required=False,
                        default="snap-to-bucket")
    parser.add_argument("--type", help="volume type (default: %(default)s)",
                        required=False, default="gp2",
                        choices=['standard', 'io1', 'gp2', 'sc1', 'st1'])
    parser.add_argument("--storage-class", help="storage class for S3 objects " +
                        "(default: %(default)s)", required=False,
                        default="STANDARD",
                        choices=['STANDARD', 'REDUCED_REDUNDANCY',
                                 'STANDARD_IA', 'ONEZONE_IA', 'GLACIER',
                                 'INTELLIGENT_TIERING', 'DEEP_ARCHIVE'])
    parser.add_argument("-m", "--mount", help="mount point for disks " +
                        "(default: %(default)s)", required=False,
                        metavar="DIR", default="/mnt/snaps")
    parser.add_argument("-d", "--delete", help="delete snapshot after " +
                        "transfer. Use with caution! (default: %(default)s)",
                        required=False, action="store_true", default=False)
    parser.add_argument("-s", "--split", help="split tar in chunks no bigger " +
                        "than (allowed suffix b,k,m,g,t) (default: %(default)s)",
                        metavar="SIZE", required=False, default="5t",
                        type=split_size)
    parser.add_argument("-g", "--gzip", help="compress tar with gzip",
                        required=False, action="store_true", default=False)
    parser.add_argument("-r", "--restore", help="restore a snapshot",
                        required=False, action="store_true", default=False)
    parser.add_argument("-k", "--key", help="key of the snapshot folder to " +
                        "restore (required if restoring)", default=None,
                        required=False)
    parser.add_argument("--boot", help="was the snapshot a bootable volume?",
                        action="store_true", default=False, required=False)
    parser.add_argument("--restore-dir", help="directory to store S3 objects " +
                        "for restoring (default: %(default)s)",
                        default="/tmp/snap-to-bucket", required=False)
    args = parser.parse_args()

    if os.geteuid() != 0:
        parser.exit(5,
                    "You need to have root privileges to run this script.\n" +
                    "Please try again, this time using 'sudo'. Exiting.\n")

    main(args)


if __name__ == '__main__':
    entrypoint()
