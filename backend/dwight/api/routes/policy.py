"""Policy screen + gateway config export. Owner: 14. FIXTURE until real=... is set.
"Apply" must write the LiteLLM config under config.POLICY_OUT_DIR and store a policies row.
The Customer's gateway enforces it, not Dwight (ADR 0002)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from dwight.api.contract import Policy, PolicyList, PolicyOptions, PolicyRender, PolicyRequest
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()

policy_options = Endpoint("policy_options", PolicyOptions, real=None)
policy_render = Endpoint("policy_render", PolicyRender, real=None)
policy_apply = Endpoint("policy_apply", Policy, real=None)
policies = Endpoint("policies", PolicyList, real=None)


@router.get("/api/policy/options", response_model=PolicyOptions)
def get_policy_options(conn=Depends(get_conn)):
    return policy_options.serve(conn)


@router.post("/api/policy/render", response_model=PolicyRender)
def render_policy(req: PolicyRequest, conn=Depends(get_conn)):
    return policy_render.serve(conn, req=req)


@router.post("/api/policy/apply", response_model=Policy)
def apply_policy(req: PolicyRequest, conn=Depends(get_conn)):
    return policy_apply.serve(conn, req=req)


@router.get("/api/policies", response_model=PolicyList)
def list_policies(conn=Depends(get_conn)):
    return policies.serve(conn)
