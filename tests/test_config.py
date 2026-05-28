from pathlib import Path

from endodigest.config import load_config, load_yamlish, validate_config


def test_config_example_loads_and_validates():
    config = load_config(Path("config/config.example.yml"))
    errors, warnings = validate_config(config)
    assert errors == []
    assert any("optional secret" in warning for warning in warnings)


def test_seed_queries_include_required_entities():
    seeds = load_yamlish(Path("config/seed_queries.yml"))
    flattened = " ".join(value for values in seeds.values() for value in values)
    for term in ["Ziwig Endotest", "HerResolve", "PromarkerEndo", "99mTc-maraciclatide"]:
        assert term in flattened


def test_env_override_for_llm_model(monkeypatch):
    monkeypatch.setenv("ENDODIGEST_LLM_MODEL", "gpt-test")
    config = load_config(Path("config/config.example.yml"))
    assert config["llm"]["model"] == "gpt-test"
