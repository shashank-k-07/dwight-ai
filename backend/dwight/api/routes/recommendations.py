"""Recommendations. Owner: 09 (12 adds draft_id, 13 adds measured_drop, 14 reads policy_prefill).
FIXTURE until real=... is set."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from dwight.api.contract import RecommendationList
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

initiative_recommendations = Endpoint("initiative_recommendations", RecommendationList, real=None)
recommendations = Endpoint("recommendations", RecommendationList, real=None)


@router.get("/api/initiatives/{initiative_id}/recommendations", response_model=RecommendationList)
def list_initiative_recommendations(initiative_id: str, conn=Depends(get_conn)):
    return initiative_recommendations.serve(conn, key=initiative_id, initiative_id=initiative_id)


@router.get("/api/recommendations", response_model=RecommendationList)
def list_recommendations(target_type: Optional[str] = None, conn=Depends(get_conn)):
    """All Recommendations, optionally filtered by target_type (team | policy | initiative).
    The fixture ignores the filter."""
    return recommendations.serve(conn, target_type=target_type)
