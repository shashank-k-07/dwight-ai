"""Generator parameters: data/synthetic/params.yaml, overlaid with
data/synthetic/calibration.yaml when `python -m dwight.synth calibrate` has
measured the real layer."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from dwight import config

SYNTH_DIR = config.DATA_DIR / "synthetic"          # generator inputs (label-bearing: the pipeline never reads them)
PARAMS_PATH = SYNTH_DIR / "params.yaml"
CALIBRATION_PATH = SYNTH_DIR / "calibration.yaml"
CONTENT_PATH = SYNTH_DIR / "content_library.json"
OTLP_OUT_DIR = config.DATA_DIR / "otlp" / "synthetic"
REAL_OTLP_DIR = config.DATA_DIR / "otlp" / "real"
GROUND_TRUTH_PATH = config.GROUND_TRUTH_DIR / "synthetic_sessions.jsonl"
SUMMARY_PATH = config.GROUND_TRUTH_DIR / "synthetic_summary.json"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(path: Path | None = None, calibration: Path | None = CALIBRATION_PATH) -> dict[str, Any]:
    params = yaml.safe_load(Path(path or PARAMS_PATH).read_text())
    if calibration is not None and Path(calibration).exists():
        cal = yaml.safe_load(Path(calibration).read_text()) or {}
        params = deep_merge(params, cal.get("overrides") or {})
        params["_calibrated_from"] = cal.get("source")
    return params
