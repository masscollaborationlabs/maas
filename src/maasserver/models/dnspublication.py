# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""DNS publication model objects."""

__all__ = [
    "DNSPublication",
]

from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
)
from django.db.models import (
    Manager,
    Model,
)
from django.db.models.fields import (
    CharField,
    DateTimeField,
    IntegerField,
)
from maasserver import DefaultMeta
from maasserver.sequence import (
    INT_MAX,
    Sequence,
)

# A DNS zone's serial is a 32-bit integer. Also, we start with the value 1
# because 0 has special meaning for some DNS servers. Even if we control the
# DNS server we use, better safe than sorry.
zone_serial = Sequence(
    'maasserver_zone_serial_seq', increment=1, minvalue=1, maxvalue=INT_MAX,
    owner='maasserver_dnspublication.serial')


def next_serial():
    return next(zone_serial)


class DNSPublicationManager(Manager):
    """Manager for DNS publishing records."""

    def get_most_recent(self):
        """Return the most recently inserted `DNSPublication`."""
        return self.order_by("-id")[0]

    def collect_garbage(self):
        """Delete all but the most recently inserted `DNSPublication`."""
        self.filter(id__lt=self.get_most_recent().id).delete()


class DNSPublication(Model):
    """A row in this table denotes a DNS publication request.

    Typically this will be populated by a trigger within the database. A
    listeners in regiond will be notified and consult the most recent record
    in this table. This way we can consistently publish zones with the same
    serial in an HA environment, and newly starting regiond processes can
    immediately be consistent with their peers.
    """

    class Meta(DefaultMeta):
        """Needed for South to recognize this model."""

    objects = DNSPublicationManager()

    # The serial number with which to publish the zone. We don't use the
    # primary key for this because zone serials are allowed to cycle.
    serial = IntegerField(
        editable=False, null=False, default=next_serial, unique=False,
        validators=(
            MinValueValidator(zone_serial.minvalue),
            MaxValueValidator(zone_serial.maxvalue),
        ))

    # This field is informational.
    created = DateTimeField(
        editable=False, null=False, auto_now=False, auto_now_add=True)

    # This field is informational.
    source = CharField(
        editable=False, max_length=255, null=False, blank=True,
        help_text="A brief explanation why DNS was published.")
