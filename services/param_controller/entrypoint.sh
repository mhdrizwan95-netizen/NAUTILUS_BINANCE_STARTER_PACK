#!/usr/bin/env sh
set -e

# Ensure /shared is writable by appuser when mounted as a named volume owned by root
if [ -d /shared ]; then
  chown -R appuser:appuser /shared 2>/dev/null || true
fi

# Execute command (container runs as root but shared volume is writable)
exec "$@"
