from pathlib import Path

import yaml

BASE = yaml.safe_load(Path("gateway/config.yaml").read_text())
OBS = yaml.safe_load(Path("gateway/config.observability.yaml").read_text())
COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text())


def names(config):
    return [m["model_name"] for m in config["model_list"]]


def test_both_gateway_configs_serve_the_same_models_and_fallbacks():
    assert BASE["model_list"] == OBS["model_list"]
    assert BASE["router_settings"] == OBS["router_settings"]


def test_master_key_comes_from_the_environment():
    for config in (BASE, OBS):
        assert config["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"


def test_ollama_models_point_at_the_ollama_service():
    for model in BASE["model_list"]:
        params = model["litellm_params"]
        if params["model"].startswith("ollama"):
            assert params["api_base"] == "http://ollama:11434"


def test_fallbacks_only_reference_served_models():
    served = set(names(BASE))
    for rule in BASE["router_settings"]["fallbacks"]:
        for primary, backups in rule.items():
            assert primary in served
            assert set(backups) <= served and primary not in backups


def test_every_ollama_model_is_pulled_by_the_init_job():
    pulled = COMPOSE["services"]["ollama-init"]["environment"]["PLATFORM_MODELS"]
    default = pulled.split(":-", 1)[1].rstrip("}").split()
    for model in BASE["model_list"]:
        params = model["litellm_params"]
        if params["model"].startswith("ollama"):
            assert params["model"].split("/", 1)[1] in default


def test_only_the_observability_config_sends_traces():
    assert "success_callback" not in BASE["litellm_settings"]
    assert OBS["litellm_settings"]["success_callback"] == ["langfuse"]
    assert OBS["litellm_settings"]["failure_callback"] == ["langfuse"]
