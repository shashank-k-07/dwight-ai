"""Every endpoint has a fixture, and every fixture matches the frozen contract."""
import json

from dwight import config
from dwight.api import main  # noqa: F401  (imports all routes, registering Endpoints)
from dwight.api.serving import ENDPOINTS


def _bodies(name):
    data = json.loads((config.API_FIXTURES_DIR / f"{name}.json").read_text())
    return list(data["items"].values()) if "_keyed_by" in data else [data]


def test_every_endpoint_has_a_valid_fixture():
    assert ENDPOINTS
    for name, ep in ENDPOINTS.items():
        for body in _bodies(name):
            ep.model.model_validate({**body, "source": "fixture"})


def _money_objects(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not k.endswith("_usd"), f"bare dollar field {path}.{k}: use a Money object"
            if isinstance(v, dict) and "usd" in v:
                assert v.get("kind") in ("measured", "estimated"), f"{path}.{k} has no Measured/Estimated kind"
            _money_objects(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _money_objects(v, f"{path}[{i}]")


def test_no_dollar_figure_without_a_kind():
    for name in ENDPOINTS:
        for body in _bodies(name):
            _money_objects(body, name)
