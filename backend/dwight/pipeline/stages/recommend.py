"""Stage: recommend (ticket 09). STUB: the owning ticket replaces run().

Recommendation engine: findings + RecurringDiscoveries + Practice Library + Infra Profile -> Recommendations (GLM writes, code prices)

Reads:  waste_findings, recurring_discoveries, initiatives, data/company/practices.yaml, data/company/infra_profile.yaml
Writes: recommendations (usd + kind attached by code, never by GLM)
Reject+retry output without a real practice_id and >= 1 real infra_ref.
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 60
TICKET = "09"
DESCRIPTION = "Recommendation engine: findings + RecurringDiscoveries + Practice Library + Infra Profile -> Recommendations (GLM writes, code prices)"


def run(conn, args):
    raise NotImplementedYet("stage 'recommend' not built yet (ticket 09)")
