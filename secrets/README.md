# secrets/

This folder holds one file per secret, created by `aiplat secrets init`. Every file except this README is gitignored. Compose mounts the files as Docker secrets under `/run/secrets/`.
