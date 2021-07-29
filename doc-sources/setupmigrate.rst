.. _migrate:

Migrate
********

Tag the snapshots to migrate
===============================

The script fetches the snapshots which requires to be migrated using the tags.

The default tag used is ``snap-to-bucket`` but can be overridden using the
``-t/--tag`` from the input flags.

The tags should hold the value ``migrate`` to be picked by the script.

Once the snapshot is moved, the tag's value will be replaced with
``transferred``.

Backup
=========

Make sure to tag the snapshots and run the script with root privileges as the
script needs to mount/unmount volumes.

* Runing from source

.. code-block:: bash

    pipenv run snap_to_bucket --bucket <bucket>

* Runing from install

.. code-block:: bash

    snap_to_bucket --bucket <bucket>

If you have used different tags on snapshots, use ``-t/--tag`` option.

If you want to mount the devices on different location, use ``-m/--mount`` option.

To change the type of volume, use ``--type`` option (like ``io1`` for higher
throughput).

The ``io1``, ``io2`` and ``gp3`` allow to provide additional IOPS, which can be
provided with ``--iops`` flag. ``gp3`` also allows setting the throughput of
the volume and can be set with ``--throughput`` flag.

The default storage class used for S3 objects will be STANDARD. To use other
classes like STANDARD_IA or even GLACIER, use ``--storage-class`` option.

If you want to delete the snapshot once they are transferred, use ``-d/--delete``
option. Use this option with caution as this step cannot be undone.

Make sure to run as root user as several permissions are required to mount a
device.

Backup huge data
==================

The tool allows you to split the resultant tar into smaller tars. To do so, use
the ``-s/--split`` flag and define the size of each part. While restoring, the
script can list all of the tars in the given folder and reassemble based on
part number.

Since the S3 has a limit on object size, a single split can not be larger than
5TB (the default value).
