"""Stage: draft (ticket 12). STUB: the owning ticket replaces run().

Drafter: common path -> initiative doc, repeated Discoveries -> memory file; attach to Recommendation; price Estimated Saving

Reads:  recurring_discoveries, discoveries, sessions.summary, company-docs/ (re-fetched fresh by resource_id, dwight.company.company_doc_path)
Writes: drafts, recommendations.draft_id / usd / kind; files under out/drafts/
Never read staging_content or any stored prompt.
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 70
TICKET = "12"
DESCRIPTION = "Drafter: common path -> initiative doc, repeated Discoveries -> memory file; attach to Recommendation; price Estimated Saving"


def run(conn, args):
    raise NotImplementedYet("stage 'draft' not built yet (ticket 12)")
