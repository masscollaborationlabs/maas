# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from fastapi import Depends, Response

from maasapiserver.common.api.base import Handler, handler
from maasapiserver.common.api.models.responses.errors import (
    NotFoundBodyResponse,
    NotFoundResponse,
    ValidationErrorBodyResponse,
)
from maasapiserver.v3.api import services
from maasapiserver.v3.api.public.models.requests.query import (
    TokenPaginationParams,
)
from maasapiserver.v3.api.public.models.responses.subnets import (
    SubnetResponse,
    SubnetsListResponse,
)
from maasapiserver.v3.auth.base import check_permissions
from maasapiserver.v3.constants import V3_API_PREFIX
from maasservicelayer.auth.jwt import UserRole
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.subnets import SubnetClauseFactory
from maasservicelayer.services import ServiceCollectionV3


class SubnetsHandler(Handler):
    """Subnets API handler."""

    TAGS = ["Subnets"]

    @handler(
        path="/fabrics/{fabric_id}/vlans/{vlan_id}/subnets",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {"model": SubnetsListResponse},
            422: {"model": ValidationErrorBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(check_permissions(required_roles={UserRole.USER}))
        ],
    )
    async def list_fabric_vlan_subnets(
        self,
        fabric_id: int,
        vlan_id: int,
        token_pagination_params: TokenPaginationParams = Depends(),
        services: ServiceCollectionV3 = Depends(services),
    ) -> Response:
        query = QuerySpec(
            where=SubnetClauseFactory.and_clauses(
                [
                    SubnetClauseFactory.with_fabric_id(fabric_id),
                    SubnetClauseFactory.with_vlan_id(vlan_id),
                ]
            )
        )
        subnets = await services.subnets.list(
            token=token_pagination_params.token,
            size=token_pagination_params.size,
            query=query,
        )
        return SubnetsListResponse(
            items=[
                SubnetResponse.from_model(
                    subnet=subnet,
                    self_base_hyperlink=f"{V3_API_PREFIX}/fabrics/{fabric_id}/vlans/{vlan_id}/subnets",
                )
                for subnet in subnets.items
            ],
            next=(
                f"{V3_API_PREFIX}/fabrics/{fabric_id}/vlans/{vlan_id}/subnets?"
                f"{TokenPaginationParams.to_href_format(subnets.next_token, token_pagination_params.size)}"
                if subnets.next_token
                else None
            ),
        )

    @handler(
        path="/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": SubnetResponse,
                "headers": {
                    "ETag": {"description": "The ETag for the resource"}
                },
            },
            404: {"model": NotFoundBodyResponse},
            422: {"model": ValidationErrorBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(check_permissions(required_roles={UserRole.USER}))
        ],
    )
    async def get_fabric_vlan_subnet(
        self,
        fabric_id: int,
        vlan_id: int,
        subnet_id: int,
        response: Response,
        services: ServiceCollectionV3 = Depends(services),
    ) -> Response:
        subnet = await services.subnets.get_by_id(
            fabric_id, vlan_id, subnet_id
        )
        if not subnet:
            return NotFoundResponse()

        response.headers["ETag"] = subnet.etag()
        return SubnetResponse.from_model(
            subnet=subnet,
            self_base_hyperlink=f"{V3_API_PREFIX}/fabrics/{fabric_id}/vlans/{vlan_id}/subnets",
        )
