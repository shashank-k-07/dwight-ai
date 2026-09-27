"""Initiative classifier (ticket 06, build-spec §4.3).

Per Session: one model call reads the staged prompt content and returns a
redacted one-line summary, the Initiative (picked from the known org.yaml
Initiatives), complexity (low/med/high) and Discoveries. Code builds the Trail
from read-type tool calls. Then the raw prompt content is deleted (ADRs 0005,
0008): see dwight/classifier/run.py.

Callable pieces (ticket 08's eval and ticket 15 build on these):

    from dwight.classifier import candidates, classify_transcript, render_transcript, load_staged
    cls = classify_transcript(render_transcript(load_staged(conn, sid)), candidates())

    from dwight.classifier import pending_sessions, classify_sessions
    stats = classify_sessions(conn, pending_sessions(conn, dataset="synthetic"), workers=8)

Never reads data/ground-truth/.
"""
from dwight.classifier.model import (PROMPT_VERSION, Candidate, Classification, Discovery, candidates,
                                     classify_transcript, redact)
from dwight.classifier.run import (RunStats, classify_sessions, pending_sessions, refresh_initiative_totals,
                                   upsert_initiatives, write_result)
from dwight.classifier.trail import TrailEntry, build_trail, is_read_tool, resource_id
from dwight.classifier.transcript import load_staged, render_transcript

__all__ = ["PROMPT_VERSION", "Candidate", "Classification", "Discovery", "candidates", "classify_transcript",
           "redact", "RunStats", "classify_sessions", "pending_sessions", "refresh_initiative_totals",
           "upsert_initiatives", "write_result", "TrailEntry", "build_trail", "is_read_tool", "resource_id",
           "load_staged", "render_transcript"]
