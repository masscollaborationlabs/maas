# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Celery settings for the cluster controller.

Do not edit this file.  Instead, put custom settings in a module named
maas_local_celeryconfig.py somewhere on the PYTHONPATH.
"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
)

str = None

__metaclass__ = type

from datetime import timedelta

import celeryconfig_common
from provisioningserver.utils import import_settings

# Cluster UUID.  Will be overridden by the customized setting in the
# local MAAS Celery config.
CLUSTER_UUID = None

import_settings(celeryconfig_common)

try:
    import maas_local_celeryconfig_cluster
except ImportError:
    pass
else:
    import_settings(maas_local_celeryconfig_cluster)


CELERYBEAT_SCHEDULE = {
    'unconditional-dhcp-lease-upload': {
        'task': 'provisioningserver.tasks.upload_dhcp_leases',
        'schedule': timedelta(minutes=1),
        'options': {'queue': CLUSTER_UUID},
    },
    'report-boot-images': {
        'task': 'provisioningserver.tasks.report_boot_images',
        'schedule': timedelta(minutes=5),
        'options': {'queue': CLUSTER_UUID},
    },
}
