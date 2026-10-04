# Add a model to the platform

## Pull the model into Ollama
Add the model tag to `PLATFORM_MODELS` in your `.env` file, for example `qwen2.5:1.5b`, then run `docker compose up -d ollama-init`. The init job pulls every model in the list and exits.

## Register the model in the gateway
Add an entry to `model_list` in both `gateway/config.yaml` and `gateway/config.observability.yaml`. Use `ollama_chat/<tag>` as the model and `http://ollama:11434` as the api_base. The `model_name` is the name clients will use. Restart the gateway with `docker compose restart gateway`.

## Check and compare it
Run `aiplat models` to confirm the gateway serves it. Run `aiplat eval --models <new>,<current>` to compare it with the current default on the fixed task set before anyone depends on it. Keep the leaderboard in `reports/` with the pull request.

## Add a fallback
If the new model should fall back to another one on timeout or error, add it under `router_settings.fallbacks` in both gateway configs.
