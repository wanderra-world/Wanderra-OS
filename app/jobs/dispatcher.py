"""Deterministic tenant-fair claim ordering for H3-02 workers."""

from __future__ import annotations

import uuid


class FairWorkspaceDispatcher:
    """Round-robin eligible workspace IDs without retrieving tenant payloads."""

    def order(
        self,
        eligible: dict[uuid.UUID, int],
        *,
        limit: int,
        organization_running: int = 0,
        organization_limit: int = 100,
    ) -> tuple[uuid.UUID, ...]:
        organization_capacity = max(0, organization_limit - organization_running)
        limit = min(limit, organization_capacity)
        if limit <= 0:
            return ()
        remaining = {workspace: max(0, count) for workspace, count in eligible.items()}
        ordered: list[uuid.UUID] = []
        while len(ordered) < limit:
            progressed = False
            for workspace, count in remaining.items():
                if count <= 0 or len(ordered) >= limit:
                    continue
                ordered.append(workspace)
                remaining[workspace] = count - 1
                progressed = True
            if not progressed:
                break
        return tuple(ordered)
