# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""API handlers: `VolumeGroups`."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type

from maasserver.api.support import (
    operation,
    OperationsHandler,
)
from maasserver.api.utils import get_mandatory_param
from maasserver.enum import (
    NODE_PERMISSION,
    NODE_STATUS,
)
from maasserver.exceptions import (
    MAASAPIValidationError,
    NodeStateViolation,
)
from maasserver.forms import (
    CreateLogicalVolumeForm,
    CreateVolumeGroupForm,
    UpdateVolumeGroupForm,
)
from maasserver.models import (
    Node,
    VirtualBlockDevice,
    VolumeGroup,
)
from maasserver.utils.converters import human_readable_bytes
from piston3.utils import rc


DISPLAYED_VOLUME_GROUP_FIELDS = (
    'id',
    'uuid',
    'name',
    'devices',
    'size',
    'human_size',
    'available_size',
    'human_available_size',
    'used_size',
    'human_used_size',
    'logical_volumes',
)


class VolumeGroupsHandler(OperationsHandler):
    """Manage volume groups on a node."""
    api_doc_section_name = "Volume groups"
    update = delete = None
    fields = DISPLAYED_VOLUME_GROUP_FIELDS

    @classmethod
    def resource_uri(cls, *args, **kwargs):
        # See the comment in NodeHandler.resource_uri.
        return ('volume_groups_handler', ["system_id"])

    def read(self, request, system_id):
        """List all volume groups belonging to node.

        Returns 404 if the node is not found.
        """
        node = Node.nodes.get_node_or_404(
            system_id, request.user, NODE_PERMISSION.VIEW)
        return VolumeGroup.objects.filter_by_node(node)

    def create(self, request, system_id):
        """Create a volume group belonging to node.

        :param name: Name of the volume group.
        :param uuid: (optional) UUID of the volume group.
        :param block_devices: Block devices to add to the volume group.
        :param partitions: Partitions to add to the volume group.

        Returns 404 if the node is not found.
        Returns 409 if the node is not Ready.
        """
        node = Node.nodes.get_node_or_404(
            system_id, request.user, NODE_PERMISSION.ADMIN)
        if node.status != NODE_STATUS.READY:
            raise NodeStateViolation(
                "Cannot create volume group because the node is not Ready.")
        form = CreateVolumeGroupForm(node, data=request.data)
        if not form.is_valid():
            raise MAASAPIValidationError(form.errors)
        else:
            return form.save()


class VolumeGroupHandler(OperationsHandler):
    """Manage volume group on a node."""
    api_doc_section_name = "Volume group"
    create = None
    model = VolumeGroup
    fields = DISPLAYED_VOLUME_GROUP_FIELDS

    @classmethod
    def resource_uri(cls, volume_group=None):
        # See the comment in NodeHandler.resource_uri.
        system_id = "system_id"
        volume_group_id = "volume_group_id"
        if volume_group is not None:
            volume_group_id = volume_group.id
            node = volume_group.get_node()
            if node is not None:
                system_id = node.system_id
        return ('volume_group_handler', (system_id, volume_group_id))

    @classmethod
    def size(cls, filesystem_group):
        return filesystem_group.get_size()

    @classmethod
    def human_size(cls, filesystem_group):
        return human_readable_bytes(filesystem_group.get_size())

    @classmethod
    def available_size(cls, volume_group):
        return volume_group.get_lvm_free_space()

    @classmethod
    def human_available_size(cls, volume_group):
        return human_readable_bytes(volume_group.get_lvm_free_space())

    @classmethod
    def used_size(cls, volume_group):
        return volume_group.get_lvm_allocated_size()

    @classmethod
    def human_used_size(cls, volume_group):
        return human_readable_bytes(volume_group.get_lvm_allocated_size())

    @classmethod
    def logical_volumes(cls, volume_group):
        return volume_group.virtual_devices.all()

    @classmethod
    def devices(cls, volume_group):
        return [
            filesystem.get_parent()
            for filesystem in volume_group.filesystems.all()
        ]

    def read(self, request, system_id, volume_group_id):
        """Read volume group on node.

        Returns 404 if the node or volume group is not found.
        """
        return VolumeGroup.objects.get_object_or_404(
            system_id, volume_group_id, request.user, NODE_PERMISSION.VIEW)

    def update(self, request, system_id, volume_group_id):
        """Read volume group on node.

        :param name: Name of the volume group.
        :param uuid: UUID of the volume group.
        :param add_block_devices: Block devices to add to the volume group.
        :param remove_block_devices: Block devices to remove from the
            volume group.
        :param add_partitions: Partitions to add to the volume group.
        :param remove_partitions: Partitions to remove from the volume group.

        Returns 404 if the node or volume group is not found.
        Returns 409 if the node is not Ready.
        """
        volume_group = VolumeGroup.objects.get_object_or_404(
            system_id, volume_group_id, request.user, NODE_PERMISSION.ADMIN)
        node = volume_group.get_node()
        if node.status != NODE_STATUS.READY:
            raise NodeStateViolation(
                "Cannot update volume group because the node is not Ready.")
        form = UpdateVolumeGroupForm(volume_group, data=request.data)
        if not form.is_valid():
            raise MAASAPIValidationError(form.errors)
        else:
            return form.save()

    def delete(self, request, system_id, volume_group_id):
        """Delete volume group on node.

        Returns 404 if the node or volume group is not found.
        Returns 409 if the node is not Ready.
        """
        volume_group = VolumeGroup.objects.get_object_or_404(
            system_id, volume_group_id, request.user, NODE_PERMISSION.ADMIN)
        node = volume_group.get_node()
        if node.status != NODE_STATUS.READY:
            raise NodeStateViolation(
                "Cannot delete volume group because the node is not Ready.")
        volume_group.delete()
        return rc.DELETED

    @operation(idempotent=False)
    def create_logical_volume(self, request, system_id, volume_group_id):
        """Create a logical volume in the volume group.

        :param name: Name of the logical volume.
        :param uuid: (optional) UUID of the logical volume.
        :param size: Size of the logical volume.

        Returns 404 if the node or volume group is not found.
        Returns 409 if the node is not Ready.
        """
        volume_group = VolumeGroup.objects.get_object_or_404(
            system_id, volume_group_id, request.user, NODE_PERMISSION.ADMIN)
        node = volume_group.get_node()
        if node.status != NODE_STATUS.READY:
            raise NodeStateViolation(
                "Cannot create logical volume because the node is not Ready.")
        form = CreateLogicalVolumeForm(volume_group, data=request.data)
        if not form.is_valid():
            raise MAASAPIValidationError(form.errors)
        else:
            return form.save()

    @operation(idempotent=False)
    def delete_logical_volume(self, request, system_id, volume_group_id):
        """Delete a logical volume in the volume group.

        :param id: ID of the logical volume.

        Returns 403 if no logical volume with id.
        Returns 404 if the node or volume group is not found.
        Returns 409 if the node is not Ready.
        """
        volume_group = VolumeGroup.objects.get_object_or_404(
            system_id, volume_group_id, request.user, NODE_PERMISSION.ADMIN)
        node = volume_group.get_node()
        if node.status != NODE_STATUS.READY:
            raise NodeStateViolation(
                "Cannot delete logical volume because the node is not Ready.")
        volume_id = get_mandatory_param(request.data, 'id')
        try:
            logical_volume = volume_group.virtual_devices.get(id=volume_id)
        except VirtualBlockDevice.DoesNotExist:
            # Ignore if it doesn't exists, we still return DELETED.
            pass
        else:
            logical_volume.delete()
        return rc.DELETED
