#!/usr/bin/env sh
set -e

# Ensure /shared is writable by appuser when mounted as a named volume owned by root
if [ -d /shared ]; then
  chown -R appuser:appuser /shared 2>/dev/null || true
fi

# Drop privileges and exec the given command as appuser
exec su -s /bin/sh -c "exec \"$@\"" appuser

