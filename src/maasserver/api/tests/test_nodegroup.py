# Copyright 2013-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the NodeGroups API."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import httplib
import json
from textwrap import dedent

import bson
from django.contrib.auth.models import AnonymousUser
from django.core.urlresolvers import reverse
from maasserver.bootresources import get_simplestream_endpoint
from maasserver.enum import (
    NODEGROUP_STATUS,
    NODEGROUP_STATUS_CHOICES,
    )
from maasserver.models import (
    DownloadProgress,
    NodeGroup,
    nodegroup as nodegroup_module,
    )
from maasserver.testing.api import (
    APITestCase,
    explain_unexpected_response,
    log_in_as_normal_user,
    make_worker_client,
    MultipleUsersScenarios,
    )
from maasserver.testing.factory import factory
from maasserver.testing.oauthclient import OAuthAuthenticatedClient
from maasserver.testing.orm import (
    reload_object,
    reload_objects,
    )
from maasserver.testing.testcase import MAASServerTestCase
from maastesting.celery import CeleryFixture
from maastesting.matchers import MockCalledOnceWith
from metadataserver.enum import RESULT_TYPE
from metadataserver.fields import Bin
from metadataserver.models import (
    commissioningscript,
    NodeResult,
    )
from mock import Mock
from provisioningserver.rpc.cluster import (
    EnlistNodesFromMSCM,
    EnlistNodesFromUCSM,
    ImportBootImages,
    )
from testresources import FixtureResource
from testtools.matchers import (
    AllMatch,
    Equals,
    )


class TestNodeGroupsAPI(MultipleUsersScenarios,
                        MAASServerTestCase):
    scenarios = [
        ('anon', dict(userfactory=lambda: AnonymousUser())),
        ('user', dict(userfactory=factory.make_User)),
        ('admin', dict(userfactory=factory.make_admin)),
        ]

    resources = (
        ('celery', FixtureResource(CeleryFixture())),
        )

    def test_handler_path(self):
        self.assertEqual(
            '/api/1.0/nodegroups/', reverse('nodegroups_handler'))

    def test_reverse_points_to_nodegroups_api(self):
        self.assertEqual(
            reverse('nodegroups_handler'), reverse('nodegroups_handler'))

    def test_nodegroups_index_lists_nodegroups(self):
        # The nodegroups index lists node groups for the MAAS.
        nodegroup = factory.make_NodeGroup()
        response = self.client.get(
            reverse('nodegroups_handler'), {'op': 'list'})
        self.assertEqual(httplib.OK, response.status_code)
        self.assertEqual(
            [{
                'uuid': nodegroup.uuid,
                'status': nodegroup.status,
                'name': nodegroup.name,
                'cluster_name': nodegroup.cluster_name,
            }],
            json.loads(response.content))


class TestNodeGroupAPI(APITestCase):

    resources = (
        ('celery', FixtureResource(CeleryFixture())),
        )

    def test_handler_path(self):
        self.assertEqual(
            '/api/1.0/nodegroups/name/',
            reverse('nodegroup_handler', args=['name']))

    def test_GET_returns_node_group(self):
        nodegroup = factory.make_NodeGroup()
        response = self.client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]))
        self.assertEqual(httplib.OK, response.status_code)
        self.assertEqual(
            nodegroup.uuid, json.loads(response.content).get('uuid'))

    def test_GET_returns_404_for_unknown_node_group(self):
        response = self.client.get(
            reverse(
                'nodegroup_handler',
                args=[factory.make_name('nodegroup')]))
        self.assertEqual(httplib.NOT_FOUND, response.status_code)

    def test_PUT_reserved_to_admin_users(self):
        nodegroup = factory.make_NodeGroup()
        response = self.client_put(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'name': factory.make_name("new-name")})

        self.assertEqual(httplib.FORBIDDEN, response.status_code)

    def test_PUT_updates_nodegroup(self):
        # The api allows the updating of a NodeGroup.
        nodegroup = factory.make_NodeGroup()
        self.become_admin()
        new_name = factory.make_name("new-name")
        new_cluster_name = factory.make_name("new-cluster-name")
        new_status = factory.pick_choice(
            NODEGROUP_STATUS_CHOICES, but_not=[nodegroup.status])
        response = self.client_put(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'name': new_name,
                'cluster_name': new_cluster_name,
                'status': new_status,
            })

        self.assertEqual(httplib.OK, response.status_code, response.content)
        nodegroup = reload_object(nodegroup)
        self.assertEqual(
            (new_name, new_cluster_name, new_status),
            (nodegroup.name, nodegroup.cluster_name, nodegroup.status))

    def test_PUT_updates_nodegroup_validates_data(self):
        nodegroup, _ = factory.make_unrenamable_NodeGroup_with_Node()
        self.become_admin()
        new_name = factory.make_name("new-name")
        response = self.client_put(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'name': new_name})

        parsed_result = json.loads(response.content)

        self.assertEqual(httplib.BAD_REQUEST, response.status_code)
        self.assertIn(
            "Can't rename DNS zone",
            parsed_result['name'][0])

    def test_accept_accepts_nodegroup(self):
        nodegroups = [factory.make_NodeGroup() for _ in range(3)]
        uuids = [nodegroup.uuid for nodegroup in nodegroups]
        self.become_admin()
        response = self.client.post(
            reverse('nodegroups_handler'),
            {
                'op': 'accept',
                'uuid': uuids,
            })
        self.assertEqual(
            (httplib.OK, "Nodegroup(s) accepted."),
            (response.status_code, response.content))
        self.assertThat(
            [nodegroup.status for nodegroup in
             reload_objects(NodeGroup, nodegroups)],
            AllMatch(Equals(NODEGROUP_STATUS.ACCEPTED)))

    def test_accept_reserved_to_admin(self):
        response = self.client.post(
            reverse('nodegroups_handler'),
            {
                'op': 'accept',
                'uuid': factory.make_string(),
            })
        self.assertEqual(httplib.FORBIDDEN, response.status_code)

    def test_reject_rejects_nodegroup(self):
        nodegroups = [factory.make_NodeGroup() for _ in range(3)]
        uuids = [nodegroup.uuid for nodegroup in nodegroups]
        self.become_admin()
        response = self.client.post(
            reverse('nodegroups_handler'),
            {
                'op': 'reject',
                'uuid': uuids,
            })
        self.assertEqual(
            (httplib.OK, "Nodegroup(s) rejected."),
            (response.status_code, response.content))
        self.assertThat(
            [nodegroup.status for nodegroup in
             reload_objects(NodeGroup, nodegroups)],
            AllMatch(Equals(NODEGROUP_STATUS.REJECTED)))

    def test_reject_reserved_to_admin(self):
        response = self.client.post(
            reverse('nodegroups_handler'),
            {
                'op': 'reject',
                'uuid': factory.make_string(),
            })
        self.assertEqual(httplib.FORBIDDEN, response.status_code)

    def test_import_boot_images_for_all_accepted_clusters(self):
        self.become_admin()
        mock_getClientFor = self.patch(nodegroup_module, 'getClientFor')
        accepted_nodegroups = [
            factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED),
            factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED),
        ]
        factory.make_NodeGroup(status=NODEGROUP_STATUS.REJECTED)
        factory.make_NodeGroup(status=NODEGROUP_STATUS.PENDING)
        response = self.client.post(
            reverse('nodegroups_handler'), {'op': 'import_boot_images'})
        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))
        expected_uuids = [
            nodegroup.uuid
            for nodegroup in accepted_nodegroups
            ]
        called_uuids = [
            client_call[0][0]
            for client_call in mock_getClientFor.call_args_list
            ]
        self.assertItemsEqual(expected_uuids, called_uuids)

    def test_import_boot_images_denied_if_not_admin(self):
        user = factory.make_User()
        client = OAuthAuthenticatedClient(user)
        response = client.post(
            reverse('nodegroups_handler'), {'op': 'import_boot_images'})
        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))

    def test_report_download_progress_accepts_new_download(self):
        nodegroup = factory.make_NodeGroup()
        filename = factory.make_string()
        client = make_worker_client(nodegroup)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'op': 'report_download_progress',
                'filename': filename,
            })
        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))

        progress = DownloadProgress.objects.get(nodegroup=nodegroup)
        self.assertEqual(nodegroup, progress.nodegroup)
        self.assertEqual(filename, progress.filename)
        self.assertIsNone(progress.size)
        self.assertIsNone(progress.bytes_downloaded)
        self.assertEqual('', progress.error)

    def test_report_download_progress_updates_ongoing_download(self):
        progress = factory.make_DownloadProgress_incomplete()
        client = make_worker_client(progress.nodegroup)
        new_bytes_downloaded = progress.bytes_downloaded + 1

        response = client.post(
            reverse('nodegroup_handler', args=[progress.nodegroup.uuid]),
            {
                'op': 'report_download_progress',
                'filename': progress.filename,
                'bytes_downloaded': new_bytes_downloaded,
            })
        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))

        progress = reload_object(progress)
        self.assertEqual(new_bytes_downloaded, progress.bytes_downloaded)

    def test_report_download_progress_rejects_invalid_data(self):
        progress = factory.make_DownloadProgress_incomplete()
        client = make_worker_client(progress.nodegroup)

        response = client.post(
            reverse('nodegroup_handler', args=[progress.nodegroup.uuid]),
            {
                'op': 'report_download_progress',
                'filename': progress.filename,
                'bytes_downloaded': -1,
            })
        self.assertEqual(
            httplib.BAD_REQUEST, response.status_code,
            explain_unexpected_response(httplib.BAD_REQUEST, response))

    def test_probe_and_enlist_ucsm_adds_ucsm(self):
        nodegroup = factory.make_NodeGroup()
        url = 'http://url'
        username = factory.make_name('user')
        password = factory.make_name('password')
        self.become_admin()

        getClientFor = self.patch(nodegroup_module, 'getClientFor')
        client = getClientFor.return_value
        nodegroup = factory.make_NodeGroup()

        response = self.client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'op': 'probe_and_enlist_ucsm',
                'url': url,
                'username': username,
                'password': password,
            })

        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))

        self.expectThat(
            client,
            MockCalledOnceWith(
                EnlistNodesFromUCSM, url=url, username=username,
                password=password))

    def test_probe_and_enlist_mscm_adds_mscm(self):
        nodegroup = factory.make_NodeGroup()
        host = 'http://host'
        username = factory.make_name('user')
        password = factory.make_name('password')
        self.become_admin()

        getClientFor = self.patch(nodegroup_module, 'getClientFor')
        client = getClientFor.return_value
        nodegroup = factory.make_NodeGroup()

        response = self.client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'op': 'probe_and_enlist_mscm',
                'host': host,
                'username': username,
                'password': password,
            })

        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))

        self.expectThat(
            client,
            MockCalledOnceWith(
                EnlistNodesFromMSCM, host=host, username=username,
                password=password))


class TestNodeGroupAPIAuth(MAASServerTestCase):
    """Authorization tests for nodegroup API."""

    example_lshw_details = dedent("""\
        <?xml version="1.0" standalone="yes"?>
        <list><node id="dunedin" /></list>
        """).encode("ascii")

    example_lshw_details_bin = bson.binary.Binary(example_lshw_details)

    def set_lshw_details(self, node, data):
        NodeResult.objects.store_data(
            node, commissioningscript.LSHW_OUTPUT_NAME,
            script_result=0, result_type=RESULT_TYPE.COMMISSIONING,
            data=Bin(data))

    example_lldp_details = dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <lldp label="LLDP neighbors">%d</lldp>
        """).encode("ascii")

    example_lldp_details_bin = bson.binary.Binary(example_lldp_details)

    def set_lldp_details(self, node, data):
        NodeResult.objects.store_data(
            node, commissioningscript.LLDP_OUTPUT_NAME,
            script_result=0, result_type=RESULT_TYPE.COMMISSIONING,
            data=Bin(data))

    def test_nodegroup_requires_authentication(self):
        nodegroup = factory.make_NodeGroup()
        response = self.client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]))
        self.assertEqual(httplib.UNAUTHORIZED, response.status_code)

    def test_nodegroup_list_nodes_requires_authentication(self):
        nodegroup = factory.make_NodeGroup()
        response = self.client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'list_nodes'})
        self.assertEqual(httplib.UNAUTHORIZED, response.status_code)

    def test_nodegroup_list_nodes_does_not_work_for_normal_user(self):
        nodegroup = factory.make_NodeGroup()
        log_in_as_normal_user(self.client)

        response = self.client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'list_nodes'})

        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))

    def test_nodegroup_list_nodes_works_for_nodegroup_worker(self):
        nodegroup = factory.make_NodeGroup()
        node = factory.make_Node(nodegroup=nodegroup)
        client = make_worker_client(nodegroup)

        response = client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'list_nodes'})

        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))
        parsed_result = json.loads(response.content)
        self.assertItemsEqual([node.system_id], parsed_result)

    def test_nodegroup_list_nodes_works_for_admin(self):
        nodegroup = factory.make_NodeGroup()
        admin = factory.make_admin()
        client = OAuthAuthenticatedClient(admin)
        node = factory.make_Node(nodegroup=nodegroup)

        response = client.get(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'list_nodes'})

        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))
        parsed_result = json.loads(response.content)
        self.assertItemsEqual([node.system_id], parsed_result)

    def test_nodegroup_import_boot_images_calls_ImportBootImages(self):
        sources = [get_simplestream_endpoint()]
        fake_client = Mock()
        mock_getClientFor = self.patch(nodegroup_module, 'getClientFor')
        mock_getClientFor.return_value = fake_client
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED)

        admin = factory.make_admin()
        client = OAuthAuthenticatedClient(admin)
        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'import_boot_images'})
        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))
        self.assertThat(
            fake_client,
            MockCalledOnceWith(ImportBootImages, sources=sources))

    def test_nodegroup_import_boot_images_denied_if_not_admin(self):
        nodegroup = factory.make_NodeGroup()
        user = factory.make_User()
        client = OAuthAuthenticatedClient(user)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'import_boot_images'})

        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))

    def make_details_request(self, client, nodegroup):
        system_ids = {node.system_id for node in nodegroup.node_set.all()}
        return client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'details', 'system_ids': system_ids})

    def test_details_requires_authentication(self):
        nodegroup = factory.make_NodeGroup()
        response = self.make_details_request(self.client, nodegroup)
        self.assertEqual(httplib.UNAUTHORIZED, response.status_code)

    def test_details_refuses_nonworker(self):
        log_in_as_normal_user(self.client)
        nodegroup = factory.make_NodeGroup()
        response = self.make_details_request(self.client, nodegroup)
        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))

    def test_details_returns_details(self):
        nodegroup = factory.make_NodeGroup()
        node = factory.make_Node(nodegroup=nodegroup)
        self.set_lshw_details(node, self.example_lshw_details)
        self.set_lldp_details(node, self.example_lldp_details)
        client = make_worker_client(nodegroup)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'details', 'system_ids': [node.system_id]})

        self.assertEqual(httplib.OK, response.status_code)
        parsed_result = bson.BSON(response.content).decode()
        self.assertDictEqual(
            {
                node.system_id: {
                    "lshw": self.example_lshw_details_bin,
                    "lldp": self.example_lldp_details_bin,
                },
            },
            parsed_result)

    def test_details_allows_admin(self):
        nodegroup = factory.make_NodeGroup()
        node = factory.make_Node(nodegroup=nodegroup)
        user = factory.make_admin()
        client = OAuthAuthenticatedClient(user)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'details', 'system_ids': [node.system_id]})

        self.assertEqual(httplib.OK, response.status_code)
        parsed_result = bson.BSON(response.content).decode()
        self.assertDictEqual(
            {
                node.system_id: {
                    "lshw": None,
                    "lldp": None,
                },
            },
            parsed_result)

    def test_empty_details(self):
        # Empty details are passed through.
        nodegroup = factory.make_NodeGroup()
        node = factory.make_Node(nodegroup=nodegroup)
        self.set_lshw_details(node, b'')
        self.set_lldp_details(node, b'')
        client = make_worker_client(nodegroup)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {'op': 'details', 'system_ids': [node.system_id]})

        self.assertEqual(httplib.OK, response.status_code)
        parsed_result = bson.BSON(response.content).decode()
        self.assertDictEqual(
            {
                node.system_id: {
                    "lshw": bson.binary.Binary(b""),
                    "lldp": bson.binary.Binary(b""),
                },
            },
            parsed_result)

    def test_details_does_not_see_other_node_groups(self):
        nodegroup_mine = factory.make_NodeGroup()
        nodegroup_theirs = factory.make_NodeGroup()
        node_mine = factory.make_Node(nodegroup=nodegroup_mine)
        self.set_lshw_details(node_mine, self.example_lshw_details)
        node_theirs = factory.make_Node(nodegroup=nodegroup_theirs)
        self.set_lldp_details(node_theirs, self.example_lldp_details)
        client = make_worker_client(nodegroup_mine)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup_mine.uuid]),
            {'op': 'details',
             'system_ids': [node_mine.system_id, node_theirs.system_id]})

        self.assertEqual(httplib.OK, response.status_code)
        parsed_result = bson.BSON(response.content).decode()
        self.assertDictEqual(
            {
                node_mine.system_id: {
                    "lshw": self.example_lshw_details_bin,
                    "lldp": None,
                },
            },
            parsed_result)

    def test_details_with_no_details(self):
        # If there are no nodes, an empty map is returned.
        nodegroup = factory.make_NodeGroup()
        client = make_worker_client(nodegroup)
        response = self.make_details_request(client, nodegroup)
        self.assertEqual(httplib.OK, response.status_code)
        parsed_result = bson.BSON(response.content).decode()
        self.assertDictEqual({}, parsed_result)

    def test_POST_report_download_progress_works_for_nodegroup_worker(self):
        nodegroup = factory.make_NodeGroup()
        filename = factory.make_string()
        client = make_worker_client(nodegroup)

        response = client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'op': 'report_download_progress',
                'filename': filename,
            })

        self.assertEqual(
            httplib.OK, response.status_code,
            explain_unexpected_response(httplib.OK, response))

    def test_POST_report_download_progress_does_not_work_for_normal_user(self):
        nodegroup = factory.make_NodeGroup()
        log_in_as_normal_user(self.client)

        response = self.client.post(
            reverse('nodegroup_handler', args=[nodegroup.uuid]),
            {
                'op': 'report_download_progress',
                'filename': factory.make_string(),
            })

        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))

    def test_POST_report_download_progress_does_work_for_other_cluster(self):
        filename = factory.make_string()
        client = make_worker_client(factory.make_NodeGroup())

        response = client.post(
            reverse(
                'nodegroup_handler', args=[factory.make_NodeGroup().uuid]),
            {
                'op': 'report_download_progress',
                'filename': filename,
            })

        self.assertEqual(
            httplib.FORBIDDEN, response.status_code,
            explain_unexpected_response(httplib.FORBIDDEN, response))
