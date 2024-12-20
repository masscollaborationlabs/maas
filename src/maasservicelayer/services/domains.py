#  Copyright 2024 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

from maascommon.enums.dns import DnsUpdateAction
from maasservicelayer.context import Context
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.base import CreateOrUpdateResource
from maasservicelayer.db.repositories.domains import DomainsRepository
from maasservicelayer.models.domains import Domain
from maasservicelayer.services._base import Service
from maasservicelayer.services.dnspublications import DNSPublicationsService


class DomainsService(Service):
    def __init__(
        self,
        context: Context,
        dnspublications_service: DNSPublicationsService,
        domains_repository: DomainsRepository,
    ):
        super().__init__(context)
        self.dnspublications_service = dnspublications_service
        self.domains_repository = domains_repository

    async def get_one(self, query: QuerySpec) -> Domain | None:
        return await self.domains_repository.get_one(query=query)

    async def create(self, resource: CreateOrUpdateResource) -> Domain:
        domain = await self.domains_repository.create(resource)
        if domain.authoritative:
            await self.dnspublications_service.create_for_config_update(
                source=f"added zone {domain.name}",
                action=DnsUpdateAction.RELOAD,
            )
        return domain

    async def update_by_id(
        self, id: int, resource: CreateOrUpdateResource
    ) -> Domain:
        old_domain = await self.domains_repository.get_by_id(id=id)

        new_domain = await self.domains_repository.update_by_id(id, resource)

        source = None
        if old_domain.authoritative and not new_domain.authoritative:
            source = f"removed zone {new_domain.name}"
        elif not old_domain.authoritative and new_domain.authoritative:
            source = f"added zone {new_domain.name}"
        elif old_domain.authoritative and new_domain.authoritative:
            changes = []
            if old_domain.name != new_domain.name:
                changes.append(f"renamed to {new_domain.name}")
            if old_domain.ttl != new_domain.ttl:
                changes.append(f"ttl changed to {new_domain.ttl}")
            if changes:
                source = f"zone {old_domain.name} " + " and ".join(changes)

        if source:
            await self.dnspublications_service.create_for_config_update(
                source=source,
                action=DnsUpdateAction.RELOAD,
            )

        return new_domain

    async def delete_by_id(self, id: int) -> None:
        domain = await self.domains_repository.get_by_id(id=id)

        await self.domains_repository.delete_by_id(id)

        if domain.authoritative:
            await self.dnspublications_service.create_for_config_update(
                source=f"removed zone {domain.name}",
                action=DnsUpdateAction.RELOAD,
            )

    async def get_default_domain(self) -> Domain:
        return await self.domains_repository.get_default_domain()
