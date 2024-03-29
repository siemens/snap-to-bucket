# snap_to_bucket

![snap_to_bucket docs](https://github.com/siemens/snap-to-bucket/workflows/snap_to_bucket%20docs/badge.svg)
[![PyPI version](https://badge.fury.io/py/snap-to-bucket.svg)](https://badge.fury.io/py/snap-to-bucket)

This tool allows to move data from AWS snapshots to S3 buckets.

### Installation

#### Local installation
```console
$ git clone https://github.com/siemens/snap-to-bucket.git
$ cd snap-to-bucket
$ python3 -m pip install -U pipenv
$ pipenv install --dev --editable .
```

#### PyPi
```console
$ python3 -m pip install -U snap-to-bucket
```

### Requirements

1. The script needs to be running on an EC2 instance.
2. Minimum RAM 2 GB, recommend RAM > 6 GB.
3. The instance running the script must have IAM role attached with privileges
   to perform following operations:
    - List snapshot
    - Create volume
    - Attach volume
    - Delete volume
    - List S3 objects
    - Upload to S3
    - Download from S3

### Sample IAM policy

You can create an IAM role and attach following policy:

```json
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
```

### Tag the snapshots to migrate

The script fetches the snapshots which requires to be migrated using the tags.
The default tag used is `snap-to-bucket` but can be overridden using the
`-t/--tag` from the inputs.

The tags should hold the value `migrate` to be picked by the script.

Once the snapshot is moved, the tag's value will be replaced with `transferred`.

### Disclaimer

The tool works for snapshots with only one Linux partition. If there are more
than partition, only the first partition will be picked.
Similarly, only one partition will be created while restoring.

The script also does not encrypt your data explicitly. So, make sure the S3
bucket is secure enough and it is advisable to enable server-side encryption
with AES-256.

### Backup

Make sure to tag the snapshots and run the script with root privileges as the
script needs to mount/unmount volumes.

- Runing from source
```console
# pipenv run snap2bucket --bucket <bucket>
```
- Runing from install
```console
# snap2bucket --bucket <bucket>
```

If you have used different tags on snapshots, use `-t\--tag` option.

If you want to mount the devices on different location, use `-m\--mount` option.

To change the type of volume, use `--type` option (like `io1` for higher
throughput).

The script can also compress the tar with gzip. Use the `--gzip` option.

The default storage class used for S3 objects will be STANDARD. To use other
classes like STANDARD_IA or even GLACIER, use `--storage-class` option.

If you want to delete the snapshot once they are transferred, use `-d\--delete`
option. Use this option with caution as this step cannot be undone.

Make sure to run as root user as several permissions are required to mount a
device.

#### Backup huge data

The tool allows you to split the resultant tar into smaller tars. To do so, use
the `-s/--split` flag and define the size of each part. While restoring, the
script can list all of the tars in the given folder and reassemble based on
part number.

Since the S3 has a limit on object size, a single split can not be larger than
5TB (the default value).

### Options

```
Usage: snap2bucket [OPTIONS]

  snap2bucket is a simple tool based on boto3 to move snapshots to S3 buckets.

Options:
  --version                       Show the version and exit.
  -v, --verbose                   increase output verbosity (-vvv for more
                                  verbosity)  [x>=0]
  --proxy http_proxy              proxy to be used
  --noproxy no_proxy              comma separated list of domains which do not
                                  require proxy
  -b, --bucket BUCKET             S3 bucket to push snaps in  [required]
  -t, --tag TAG                   tag on snapshots  [default: snap-to-bucket]
  --type [standard|io1|io2|gp2|gp3|sc1|st1]
                                  volume type  [default: gp2]
  --iops INTEGER                  volume IOPS, valid only for gp3, io1 and io2
  --throughput THROUGHPUT         volume throughput in MiB/s. Valid only for
                                  gp3 volumes  [125<=x<=1000]
  --storage-class [STANDARD|REDUCED_REDUNDANCY|STANDARD_IA|ONEZONE_IA|GLACIER|INTELLIGENT_TIERING|DEEP_ARCHIVE]
                                  storage class for S3 objects  [default:
                                  STANDARD]
  -m, --mount DIR                 mount point for disks  [default: /mnt/snaps]
  -d, --delete                    delete snapshot after transfer. Use with
                                  caution!  [default: False]
  -s, --split SIZE                split tar in chunks no bigger than (allowed
                                  suffix b,k,m,g,t)  [default: 5t]
  -g, --gzip                      compress tar with gzip
  -r, --restore                   restore a snapshot
  -k, --key TEXT                  key of the snapshot folder to restore
                                  (required if restoring)
  --boot                          was the snapshot a bootable volume?
  --restore-dir DIRECTORY         directory to store S3 objects for restoring
                                  [default: /tmp/snap-to-bucket]
  -h, --help                      Show this message and exit.
```

### Files on S3

The script will store snapshots with following structure in S3:
```
snap/<snapshot-name>/<snapshot-id>-<creation-time>-<now-time>.tar
```

The snaphost name gets spaces ` ` and `/` replaces as `+` and `_` respectively.
And the date/time is in ISO 8601 format.

This section is controlled by `get_key_for_upload()` of `S3Handler`.

### Recovery

#### Manually

1. Create a new volume of the desired size in AWS and attach to an instance.
    - You can also check for `x-amz-meta-disc-size` metadata attached to the S3
      object to get the estimated size of unpacked files.
    - The meta tag `snap-volume-size` also stores the size of volume from which
      the snapshot was created.
2. Download the snapshot from S3 to the instance.
    1. If the upload was splitted, all the parts must be combined into one.
        - `cat <downloaded_parts> > <single_huge>.tar`
3. Partition the disk
    - `printf "label: dos\ntype=83\n" | sudo sfdisk <device>` if the snapshot
      was not bootable.
    - `printf "label: dos\ntype=83, bootable\n" | sudo sfdisk <device>` if the
      snapshot was bootable.
    - `# partprobe <device>` to let know the kernel of new partition table.
4. Format the disk
    - `# mke2fs -t ext4 <device_partition>`
5. Mount the partition
    - `# mount <device_partition> /mnt/snapshot`
6. Untar the downloaded file
    - `# tar --extract --verbose --file <tar_location> -C /mnt/snapshot --preserve`
7. Update the fstab
    1. Check the fstab from `/mnt/snapshot/etc/fstab`
    2. If disk was mounted from `Label`
        - Update the label of new partition `# e2label <device> <label>`
        - Check if the label was updated `# e2label <device>`
    3. If the disk was mounted using UUID
        - Get the UUID of the new device `# blkid`
        - Edit the `/mnt/snapshot/etc/fstab`
8. Update the grub if snapshot was bootable
    1. Mount the required devices
```shell
for i in /sys /proc /run /dev; do sudo mount --bind $i /mnt/snapshot$i; done
```
    2. ChRoot to mounted location
```console
# chroot /mnt/snapshot
```
    3. Reinstall and update grub
```console
# grub-install <device>
# update-grub
```
    4. Unmount the devices
```shell
for i in /sys /proc /run /dev; do sudo umount /mnt/snapshot$i; done
```
9. Unmount and detach the volume.

#### From script (experimental)

Run the script with `-r\--restore` flag and provide the bucket and the key.
- Runing from source
```console
# pipenv run snap2bucket --restore --bucket <bucket> --key <key>
```
- Runing from install
```console
# snap2bucket --restore --bucket <bucket> --key <key>
```

**Note:** The script will create new volume of size 25% more than the size of
tar or `x-amz-meta-disc-size` metadata (if available).

The value for `--key` should be the logical folder holding the tars. For example
`snap/<snapshot-name>`. The scipt will handle single file upload and split
uploads accordingly.

Use `--boot` flag if the snapshot to be restored was a bootable volume.

Restore accepts other options `--type` and `-m\--mount`.
