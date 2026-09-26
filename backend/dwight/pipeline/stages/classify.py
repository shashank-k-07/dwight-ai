"""Stage: classify (ticket 06). STUB: the owning ticket replaces run().

GLM reads staged prompt content -> summary, Initiative, complexity, Discoveries; code builds the Trail; then deletes staging

Reads:  sessions, calls, tool_calls, staging_content (the ONLY stage allowed to read it); data/company/org.yaml for Initiative names
Writes: sessions.{initiative_id, summary, complexity, classified_at}, trail_entries, discoveries, initiatives (incl. session_count, spend_usd)
MUST delete the Session's staging_content rows once classified (ADRs 0005, 0008).
MUST NOT read data/ground-truth/. Use dwight.glm.chat_json for structured output.
"""
from __future__ import annotations

from dwight.pipeline import NotImplementedYet

ORDER = 20
TICKET = "06"
DESCRIPTION = "GLM reads staged prompt content -> summary, Initiative, complexity, Discoveries; code builds the Trail; then deletes staging"


def run(conn, args):
    raise NotImplementedYet("stage 'classify' not built yet (ticket 06)")
