# Gateway is down or slow

## First look
Run `aiplat status`. It shows each service as up or DOWN with its HTTP status and latency. Then run `docker compose ps` to see which containers are unhealthy and `docker compose logs --tail 100 gateway` for the gateway's own errors.

## Gateway returns 401
The client is not sending the current master key. Check that `secrets/litellm_master_key.txt` exists and that the gateway was recreated after the last rotation.

## Gateway returns 500 or times out
Usually Ollama is still loading the model or the model was never pulled. Run `aiplat models`, check `docker compose logs ollama-init`, and try a smaller model with `aiplat chat qwen2.5-0.5b "ping"`. On CPU the first request after start-up can take much longer than later ones because the model is loaded into memory.

## Model answers are slow
Check latency per model with `aiplat eval`. Use a smaller model, lower max_tokens, or run Ollama on a GPU with `docker-compose.gpu.yml`. If one model keeps failing, the gateway sends the request to its fallback; the fallback is visible in Langfuse traces when observability is enabled.

## Langfuse shows no traces
Start the stack with `docker-compose.observability.yml`, confirm `aiplat status` shows langfuse as up, and check that the gateway logs no Langfuse authentication errors. If your Langfuse version ignores the LANGFUSE_INIT variables, create a project in the UI and copy its keys into `secrets/langfuse_public_key.txt` and `secrets/langfuse_secret_key.txt`.
