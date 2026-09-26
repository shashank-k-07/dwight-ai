"""Stage: detect (ticket 05). STUB: the owning ticket replaces run().

Waste detectors: Redundant Read, Cache Miss, Runaway Loop (Measured), Model Overkill (Estimated)

Reads:  calls, tool_calls, sessions.complexity, prices (dwight.pricing)
Writes: waste_findings (replace all rows for the Sessions processed)
Pricing rules exactly as build-spec §4.2. Tool calls on Call k are those it REQUESTED;
their results enter the input of Call k+1 onward. Never read the planted-pattern label file.
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 30
TICKET = "05"
DESCRIPTION = "Waste detectors: Redundant Read, Cache Miss, Runaway Loop (Measured), Model Overkill (Estimated)"


def run(conn, args):
    raise NotImplementedYet("stage 'detect' not built yet (ticket 05)")
