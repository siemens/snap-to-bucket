.. _recovery:

Recovery
********

Manually
============

#. Create a new volume of the desired size in AWS and attach to an instance.
    * You can also check for ``x-amz-meta-disc-size`` metadata attached to the S3
      object to get the estimated size of unpacked files.
    * The meta tag ``snap-volume-size`` also stores the size of volume from
      which the snapshot was created.

#. Download the snapshot from S3 to the instance.

#. Partition the disk
    * ``printf "label: dos\ntype=83\n" | sudo sfdisk <device>`` if the snapshot
      was not bootable.
    * ``printf "label: dos\ntype=83, bootable\n" | sudo sfdisk <device>`` if the
      snapshot was bootable.
    * ``# partprobe <device>`` to let know the kernel of new partition table.

#. Format the disk
    * ``# mke2fs -t ext4 <device_partition>``

#. Mount the partition
    * ``# mount <device_partition> /mnt/snapshot``

#. Untar the downloaded file
    * ``# tar --extract --verbose --file <tar_location> -C /mnt/snapshot --preserve``

#. Update the fstab
    #. Check the fstab from ``/mnt/snapshot/etc/fstab``
    #. If disk was mounted from ``Label``
        * Update the label of new partition ``# e2label <device> <label>``
        * Check if the label was updated ``# e2label <device>``
    #. If the disk was mounted using UUID
        * Get the UUID of the new device ``# blkid``
        * Edit the ``/mnt/snapshot/etc/fstab``

#. Update the grub if snapshot was bootable
    #. Mount the required devices
        ``for i in /sys /proc /run /dev; do sudo mount --bind $i /mnt/snapshot$i; done``
    #. ChRoot to mounted location
        ``chroot /mnt/snapshot``
    #. Reinstall and update grub
        ``grub-install <device>``
        ``update-grub``
    #. Unmount the devices
        ``for i in /sys /proc /run /dev; do sudo umount /mnt/snapshot$i; done``

#. Unmount and detach the volume.

From script (experimental)
==============================

Run the script with ``-r\--restore`` flag and provide the bucket and the key.
* Runing from source

.. code-block:: bash

    pipenv run snap_to_bucket --restore --bucket <bucket> --key <key>

* Runing from install

.. code-block:: bash

    snap_to_bucket --restore --bucket <bucket> --key <key>

**Note:** The script will create new volume of size 25% more than the size of
tar or ``x-amz-meta-disc-size`` metadata (if available).

The value for ``--key`` should be the logical folder holding the tars. For
example ``snap/<snapshot-name>``. The scipt will handle single file upload and
split uploads accordingly.

Use ``--boot`` flag if the snapshot to be restored was a bootable volume.

The flag ``--restore-dir=RESTORE_DIR`` can be used to point the directory where
object from S3 can be downloaded. It defaults to ``/tmp/snap-to-bucket``.

Restore accepts other options ``--type`` and ``-m/--mount``.
