"""Stage: common_paths (ticket 10). STUB: the owning ticket replaces run().

Per Initiative: resources read in >= 60% of Sessions -> RecurringDiscovery(form=common_path), Measured

Reads:  trail_entries, sessions.initiative_id, calls (for the input rate each Call paid)
Writes: recurring_discoveries WHERE form='common_path'
Only stored Trails, never prompt content (ADR 0008).
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 40
TICKET = "10"
DESCRIPTION = "Per Initiative: resources read in >= 60% of Sessions -> RecurringDiscovery(form=common_path), Measured"


def run(conn, args):
    raise NotImplementedYet("stage 'common_paths' not built yet (ticket 10)")
