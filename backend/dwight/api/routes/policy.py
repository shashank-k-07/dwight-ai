"""Policy screen + gateway config export. Owner: 14.
"Apply" writes the LiteLLM config under config.POLICY_OUT_DIR and stores a policies row.
The Customer's gateway enforces it, not Dwight (ADR 0002). Logic: dwight/policy_export.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dwight import policy_export
from dwight.api.contract import Policy, PolicyList, PolicyOptions, PolicyRender, PolicyRequest
from dwight.api.serving import Endpoint, get_conn

router = APIRouter()


def _checked(fn, *args):
    try:
        return fn(*args)
    except policy_export.PolicyError as e:
        raise HTTPException(400, str(e)) from e


def _options(conn, **_):
    return policy_export.options()


def _render(conn, req: PolicyRequest, **_):
    return _checked(policy_export.render, req.team, req.allowed_models)


def _apply(conn, req: PolicyRequest, **_):
    return _checked(policy_export.apply, conn, req.team, req.allowed_models)


def _policies(conn, **_):
    return policy_export.list_policies(conn)


policy_options = Endpoint("policy_options", PolicyOptions, real=_options)
policy_render = Endpoint("policy_render", PolicyRender, real=_render)
policy_apply = Endpoint("policy_apply", Policy, real=_apply)
policies = Endpoint("policies", PolicyList, real=_policies)


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
