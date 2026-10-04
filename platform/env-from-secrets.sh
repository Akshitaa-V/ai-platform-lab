#!/bin/sh
# Export every Docker secret in /run/secrets as an environment variable, then
# start the real command. For images that only read configuration from the
# environment (such as LiteLLM), this keeps secret values out of compose files,
# `docker inspect` output and the image itself.
#
#   /run/secrets/litellm_master_key  ->  LITELLM_MASTER_KEY
set -eu

if [ -d /run/secrets ]; then
  for file in /run/secrets/*; do
    [ -f "$file" ] || continue
    name=$(basename "$file" | tr '[:lower:]-' '[:upper:]_')
    case "$name" in
      ''|[0-9]*|*[!A-Z0-9_]*) echo "env-from-secrets: skipping $file (not a valid name)" >&2; continue ;;
    esac
    value=$(cat "$file")
    export "$name=$value"
  done
fi

exec "$@"
