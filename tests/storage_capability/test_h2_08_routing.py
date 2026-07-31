from __future__ import annotations

import pytest

from app.provider_capabilities.common import MutationContext, Page, VersionPrecondition
from app.provider_capabilities.storage import StorageListRequest, StorageObject, StorageObjectCreate
from app.storage_capability.contracts import StorageRoute
from app.storage_capability.service import StorageCapabilityService


class Port:
    def __init__(self, name):
        self.item = StorageObject("f", name, "text/plain", 1, "v1")
        self.calls = []

    async def list_objects(self, r):
        self.calls.append("list")
        return Page((self.item,))

    async def upload(self, i, c):
        self.calls.append("upload")
        return self.item

    async def delete(self, i, c):
        self.calls.append("delete")


class Factory:
    def __init__(self, p):
        self.p = p
        self.calls = 0

    async def canonical_port(self):
        self.calls += 1
        return self.p


class Store:
    def __init__(self, r):
        self.r = r
        self.comparisons = []

    async def route(self):
        return self.r

    async def record_comparison(self, o, e):
        self.comparisons.append(e)


class Gate:
    def __init__(self, allow=True):
        self.allow = allow

    async def require(self, p):
        if not self.allow:
            raise PermissionError("denied")


class Mutations:
    def __init__(self):
        self.values = {}
        self.approvals = []

    async def require_approval(self, a):
        self.approvals.append(a)

    async def execute_once(self, k, d, op):
        if k in self.values:
            if self.values[k][0] != d:
                raise RuntimeError("changed replay")
            return self.values[k][1]
        value = await op()
        self.values[k] = (d, value)
        return value


@pytest.mark.asyncio
async def test_shadow_returns_legacy_and_rollback_avoids_canonical():
    legacy, canonical = Port("same"), Port("same")
    factory = Factory(canonical)
    store = Store(StorageRoute.SHADOW)
    service = StorageCapabilityService(legacy, factory, store, Gate(), Mutations())
    assert (await service.list_objects(StorageListRequest())).items[
        0
    ].name == "same" and store.comparisons == [True]
    store.r = StorageRoute.LEGACY
    await service.list_objects(StorageListRequest())
    assert factory.calls == 1


@pytest.mark.asyncio
async def test_denial_precedes_provider_and_mutations_are_approved_idempotent():
    factory = Factory(Port("new"))
    denied = StorageCapabilityService(
        Port("old"), factory, Store(StorageRoute.CANONICAL), Gate(False), Mutations()
    )
    with pytest.raises(PermissionError):
        await denied.list_objects(StorageListRequest())
    assert factory.calls == 0
    port = Port("old")
    mutations = Mutations()
    service = StorageCapabilityService(
        port, Factory(Port("new")), Store(StorageRoute.LEGACY), Gate(), mutations
    )
    item = StorageObjectCreate("a", b"a", "text/plain")
    first = await service.upload(item, MutationContext("u"), approval_id="a")
    second = await service.upload(item, MutationContext("u"), approval_id="a")
    assert first == second and port.calls == ["upload"]
    with pytest.raises(ValueError, match="precondition"):
        await service.delete("f", MutationContext("d"), approval_id="a")
    await service.delete(
        "f", MutationContext("d", VersionPrecondition(version="v1")), approval_id="a"
    )
