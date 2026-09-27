import importlib


def test_model_pool_round_robins(monkeypatch):
    monkeypatch.setenv("DWIGHT_GLM_MODEL_POOL", "model-a, model-b")
    from dwight import config, glm
    importlib.reload(config)
    importlib.reload(glm)
    try:
        assert [glm.model_for() for _ in range(4)] == ["model-a", "model-b", "model-a", "model-b"]
        assert glm.model_for("some-explicit-model") == "some-explicit-model"
    finally:
        monkeypatch.delenv("DWIGHT_GLM_MODEL_POOL")
        importlib.reload(config)
        importlib.reload(glm)
