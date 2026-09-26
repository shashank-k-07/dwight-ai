"""Stage: repeated_discoveries (ticket 11). STUB: the owning ticket replaces run().

Per Initiative: cluster Discoveries (embeddings + GLM naming) -> RecurringDiscovery(form=repeated_discovery), Measured

Reads:  discoveries, sessions.initiative_id, calls (spend up to call_seq)
Writes: recurring_discoveries WHERE form='repeated_discovery'
Only stored Discoveries, never prompt content (ADR 0008). dwight.glm.embed + chat_json.
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 50
TICKET = "11"
DESCRIPTION = "Per Initiative: cluster Discoveries (embeddings + GLM naming) -> RecurringDiscovery(form=repeated_discovery), Measured"


def run(conn, args):
    raise NotImplementedYet("stage 'repeated_discoveries' not built yet (ticket 11)")
