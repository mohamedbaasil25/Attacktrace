#!/bin/sh
# Phase 5.1: runs as root (the image's default USER, before this script drops it), fixes
# ownership of the directories the app actually writes to, then execs the real command as the
# unprivileged `appuser`. Needed because bind-mounted host directories keep whatever ownership
# they already had -- including files left over from before this container ran as non-root at
# all, which is exactly what this project's own `./data/live` had (an `incidents.sqlite` from an
# earlier root-owned run, confirmed by actually running `docker compose up` against the
# non-root image and watching it fail with "attempt to write a readonly database").
set -e

for dir in /app/models /reports /data/live; do
  if [ -d "$dir" ]; then
    chown -R appuser:appuser "$dir" 2>/dev/null || true
  fi
done

# `su` (already in the base image) rather than `gosu`/`su-exec`, to avoid pulling in a binary
# from outside the base image's own package set for this one step.
exec su appuser -s /bin/sh -c 'exec "$0" "$@"' -- "$@"
