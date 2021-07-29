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
import math

import click
from pkg_resources import get_distribution

from snap_to_bucket import SnapToBucket


class VolSize(click.ParamType):
    """
    Understand the volume split size arguments
    """
    name = 'split'

    def convert(self, value, param, ctx):
        """
        Function to parse the split argument
        """
        if isinstance(value, str):
            match_result = re.match(r"""^([\d\.]+)(b|k|m|g|t)$""", value,
                                    re.RegexFlag.IGNORECASE | re.RegexFlag.MULTILINE)
            if match_result:
                size = match_result.group(1)
                split_bytes = 0
                if match_result.group(2) == "b":
                    split_bytes = float(size)
                elif match_result.group(2) == "k":
                    split_bytes = float(size) * 1024.0
                elif match_result.group(2) == "m":
                    split_bytes = float(size) * 1024.0 * 1024.0
                elif match_result.group(2) == "g":
                    split_bytes = float(size) * 1024.0 * 1024.0 * 1024.0
                elif match_result.group(2) == "t":
                    split_bytes = float(size) * 1024.0 * \
                        1024.0 * 1024.0 * 1024.0
            else:
                self.fail(
                    f'{value} not in <size><b|k|m|g|t> format',
                    param,
                    ctx,
                )
        else:
            split_bytes = float(value)
        if split_bytes > 5497558138880.0:
            self.fail(
                f'Can not have spit size greater than 5t, {value} provided',
                param,
                ctx,
            )
        if split_bytes < 5242880.0:
            self.fail(
                f'Can not have spit size lesser than 5m, {value} provided',
                param,
                ctx,
            )
        return int(math.ceil(split_bytes))


@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.version_option(get_distribution("snap_to_bucket").version)
@click.option("-v", "--verbose", help="increase output verbosity (-vvv for " +
              "more verbosity)", count=True, default=0)
@click.option("--proxy", help="proxy to be used", default=None,
              metavar="http_proxy", envvar="http_proxy")
@click.option("--noproxy", help="comma separated list of domains " +
              "which do not require proxy", default=None, metavar="no_proxy",
              envvar="no_proxy")
@click.option("-b", "--bucket", help="S3 bucket to push snaps in",
              required=True, metavar="BUCKET")
@click.option("-t", "--tag", help="tag on snapshots", default="snap-to-bucket",
              show_default=True, metavar="TAG")
@click.option("--type", help="volume type", default="gp2", show_default=True,
              type=click.Choice(['standard', 'io1', 'gp2', 'gp3', 'sc1', 'st1'],
                                case_sensitive=False))
@click.option("--storage-class", help="storage class for S3 objects",
              default="STANDARD", show_default=True,
              type=click.Choice(['STANDARD', 'REDUCED_REDUNDANCY',
                                 'STANDARD_IA', 'ONEZONE_IA', 'GLACIER',
                                 'INTELLIGENT_TIERING', 'DEEP_ARCHIVE'],
                                case_sensitive=False))
@click.option("-m", "--mount", help="mount point for disks", metavar="DIR",
              default="/mnt/snaps", show_default=True,
              type=click.Path(exists=False, dir_okay=True, writable=True,
                              file_okay=False, resolve_path=True))
@click.option("-d", "--delete", help="delete snapshot after transfer. Use " +
              "with caution!", is_flag=True, default=False, show_default=True)
@click.option("-s", "--split", help="split tar in chunks no bigger than " +
              "(allowed suffix b,k,m,g,t)  [default: 5t]", metavar="SIZE",
              default="5t", type=VolSize())
@click.option("-g", "--gzip", help="compress tar with gzip", is_flag=True,
              default=False)
@click.option("-r", "--restore", help="restore a snapshot", is_flag=True,
              default=False)
@click.option("-k", "--key", help="key of the snapshot folder to restore " +
              "(required if restoring)", default=None)
@click.option("--boot", help="was the snapshot a bootable volume?",
              is_flag=True, default=False)
@click.option("--restore-dir", help="directory to store S3 objects for " +
              "restoring", default="/tmp/snap-to-bucket", show_default=True,
              type=click.Path(exists=False, dir_okay=True, writable=True,
                              file_okay=False, resolve_path=True))
def main(verbose, proxy, noproxy, bucket, tag, type, storage_class, mount,
         delete, split, gzip, restore, key, boot, restore_dir):
    """
    snap_to_bucket is a simple tool based on boto3 to move snapshots to S3
    buckets.
    """
    if os.geteuid() != 0:
        click.echo("You need to have root privileges to run this script.\n" +
                   "Please try again, this time using 'sudo'. Exiting.",
                   err=True)
        sys.exit(5)
    snap_to_bucket = SnapToBucket(bucket, tag, verbose, type, storage_class,
                                  mount, delete, restore, key, boot,
                                  restore_dir)
    snap_to_bucket.update_proxy(proxy, noproxy)
    snap_to_bucket.update_split_size(split)
    if gzip:
        snap_to_bucket.perform_gzip()
    snap_to_bucket.initiate_migration()


if __name__ == '__main__':
    main()
