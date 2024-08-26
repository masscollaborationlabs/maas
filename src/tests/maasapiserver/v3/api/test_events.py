# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
import pytest

from maasapiserver.common.utils.date import utcnow
from maasapiserver.v3.api.models.responses.events import EventsListResponse
from maasapiserver.v3.constants import V3_API_PREFIX
from maasapiserver.v3.models.base import ListResult
from maasapiserver.v3.models.events import (
    EndpointChoicesEnum,
    Event,
    EventType,
    LoggingLevelEnum,
)
from maasapiserver.v3.services import ServiceCollectionV3
from maasapiserver.v3.services.events import EventsService
from tests.maasapiserver.v3.api.base import ApiCommonTests, Endpoint

TEST_EVENT_TYPE = EventType(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    name="TYPE_TEST",
    description="A test type",
    level=LoggingLevelEnum.AUDIT.value,
)

TEST_EVENT = Event(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    type=TEST_EVENT_TYPE,
    node_system_id="1",
    node_hostname="",
    user_id=None,
    owner="",
    ip_address=None,
    endpoint=EndpointChoicesEnum.API.value,
    user_agent="",
    description="",
    action="test",
)

TEST_EVENT_2 = Event(
    id=2,
    created=utcnow(),
    updated=utcnow(),
    type=TEST_EVENT_TYPE,
    node_system_id="2",
    node_hostname="",
    user_id=None,
    owner="",
    ip_address=None,
    endpoint=EndpointChoicesEnum.API.value,
    user_agent="",
    description="",
    action="test",
)


class TestEventsApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/events"

    @pytest.fixture
    def user_endpoints(self) -> list[Endpoint]:
        return [
            Endpoint(method="GET", path=self.BASE_PATH),
        ]

    @pytest.fixture
    def admin_endpoints(self) -> list[Endpoint]:
        return []

    async def test_list_filters(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user: AsyncClient,
    ) -> None:

        services_mock.events = Mock(EventsService)
        services_mock.events.list = AsyncMock(
            side_effect=[
                ListResult[Event](items=[TEST_EVENT], next_token=None),
                ListResult[Event](items=[TEST_EVENT_2], next_token=None),
                ListResult[Event](
                    items=[TEST_EVENT_2, TEST_EVENT], next_token=None
                ),
                ListResult[Event](
                    items=[TEST_EVENT_2], next_token=str(TEST_EVENT.id)
                ),
            ]
        )

        response = await mocked_api_client_user.get(
            f"{self.BASE_PATH}?system_id={TEST_EVENT.node_system_id}"
        )
        events_response = EventsListResponse(**response.json())
        assert len(events_response.items) == 1
        assert (
            events_response.items[0].node_system_id
            == TEST_EVENT.node_system_id
        )

        response = await mocked_api_client_user.get(
            f"{self.BASE_PATH}?system_id={TEST_EVENT_2.node_system_id}"
        )
        events_response = EventsListResponse(**response.json())
        assert len(events_response.items) == 1
        assert (
            events_response.items[0].node_system_id
            == TEST_EVENT_2.node_system_id
        )

        response = await mocked_api_client_user.get(
            f"{self.BASE_PATH}?system_id={TEST_EVENT.node_system_id}&system_id={TEST_EVENT_2.node_system_id}"
        )
        events_response = EventsListResponse(**response.json())
        assert len(events_response.items) == 2
        assert set(map(lambda x: x.node_system_id, events_response.items)) == {
            TEST_EVENT.node_system_id,
            TEST_EVENT_2.node_system_id,
        }

        response = await mocked_api_client_user.get(
            f"{self.BASE_PATH}?system_id={TEST_EVENT.node_system_id}&system_id={TEST_EVENT_2.node_system_id}&size=1"
        )
        events_response = EventsListResponse(**response.json())
        assert len(events_response.items) == 1
        next_link_params = parse_qs(urlparse(events_response.next).query)
        assert set(next_link_params["system_id"]) == {
            TEST_EVENT.node_system_id,
            TEST_EVENT_2.node_system_id,
        }
        assert next_link_params["size"][0] == "1"