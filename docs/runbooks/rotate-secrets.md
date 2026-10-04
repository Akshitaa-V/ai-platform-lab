# Rotate secrets

## When to rotate
Rotate the gateway master key when someone who had it leaves the team, when it may have appeared in a log or chat, and on a fixed schedule. Never paste a secret into an issue, a commit or a prompt.

## Rotate the gateway master key
Delete `secrets/litellm_master_key.txt`, run `aiplat secrets init` to create a new one, then run `docker compose up -d --force-recreate gateway mcp`. Both services read the key from the Docker secret at start-up. Give the new key to clients through your secret store, not by email.

## Rotate everything
`aiplat secrets init --force` replaces every secret file and regenerates `.env.observability`. Postgres keeps its old password inside its data volume, so after a full rotation either change the password inside Postgres or recreate the `langfuse-db` volume, which deletes stored traces.

## Check nothing leaked into the repository
Run `aiplat secrets check`. It scans the repository for key patterns and for the exact values in `secrets/`, and CI runs the same check on every push.
