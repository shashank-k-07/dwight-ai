"""Pass/fail checks for the storage cost reduction tasks.

Implements the check DSL in the header of data/company/storage_tasks.yaml
(json_fields, json_records, blobctl_plan, blobctl_apply; matchers equals,
bucket, bucket_list, approx). All checks of a task must pass.

    passed, notes = evaluate(task["check"], workspace_root)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _bucket(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    return v.strip().removeprefix("s3://").rstrip("/")


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "").lstrip("$"))
        except ValueError:
            return None
    return None


def match(matcher: dict, value: Any) -> bool:
    if "equals" in matcher:
        want = matcher["equals"]
        if isinstance(want, str):
            return isinstance(value, str) and value.strip() == want.strip()
        return value == want
    if "bucket" in matcher:
        return _bucket(value) == _bucket(matcher["bucket"])
    if "bucket_list" in matcher:
        want = matcher["bucket_list"]
        return (isinstance(value, list) and len(value) == len(want)
                and all(_bucket(a) == _bucket(b) for a, b in zip(value, want)))
    if "approx" in matcher:
        n = _num(value)
        return n is not None and abs(n - float(matcher["approx"])) <= float(matcher.get("abs_tol", 0))
    raise ValueError(f"unknown matcher {matcher}")


def _load_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, f"{path.name} missing"
    try:
        return json.loads(path.read_text()), None
    except json.JSONDecodeError as e:
        return None, f"{path.name} is not valid JSON: {e}"


def _state_dir(root: Path) -> Path:
    return root / ".blobctl"


def check_one(check: dict, root: Path) -> tuple[bool, str]:
    kind = check["type"]
    if kind == "json_fields":
        data, err = _load_json(root / check["path"])
        if err:
            return False, err
        if not isinstance(data, dict):
            return False, f"{check['path']} is not a JSON object"
        bad = [k for k, m in check["fields"].items() if not match(m, data.get(k))]
        return (not bad), f"{check['path']}: " + (f"wrong {bad}" if bad else "ok")
    if kind == "json_records":
        data, err = _load_json(root / check["path"])
        if err:
            return False, err
        if not isinstance(data, list):
            return False, f"{check['path']} is not a JSON array"
        key = check["key"]
        by_key = {_bucket(r.get(key)): r for r in data if isinstance(r, dict)}
        bad = []
        for name, fields in check["records"].items():
            rec = by_key.get(_bucket(name))
            if rec is None or not all(match(m, rec.get(k)) for k, m in fields.items()):
                bad.append(name)
        return (not bad), f"{check['path']}: " + (f"wrong {bad}" if bad else "ok")
    if kind == "blobctl_plan":
        plan, err = _load_json(_state_dir(root) / "plans" / f"{check['rule_id']}.json")
        if err:
            return False, f"plan {check['rule_id']}: {err}"
        trs = [[t.get("days"), t.get("storage_class")] for t in plan.get("transitions") or []]
        ok = (_bucket(plan.get("bucket")) == _bucket(check["bucket"])
              and trs == [list(t) for t in check["transitions"]]
              and plan.get("expire_days") == check["expire_days"])
        return ok, f"plan {check['rule_id']}: " + ("ok" if ok else f"got bucket={plan.get('bucket')} "
                                                   f"transitions={trs} expire={plan.get('expire_days')}")
    if kind == "blobctl_apply":
        lf = _state_dir(root) / "ledger.jsonl"
        rows = [json.loads(l) for l in lf.read_text().splitlines() if l.strip()] if lf.exists() else []
        ok = any(r.get("action") == "apply" and r.get("rule_id") == check["rule_id"]
                 and r.get("change") == check["change"] and r.get("approver") == check["approver"] for r in rows)
        return ok, f"apply {check['rule_id']}: " + ("ok" if ok else "no matching apply in the ledger")
    raise ValueError(f"unknown check type {kind}")


def evaluate(checks: list[dict], root: Path | str) -> tuple[bool, list[str]]:
    root = Path(root)
    results = [check_one(c, root) for c in checks]
    return all(ok for ok, _ in results), [note for _, note in results]
