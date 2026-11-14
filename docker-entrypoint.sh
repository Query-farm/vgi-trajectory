#!/bin/sh
# http (default): serve over HTTP on $PORT.  stdio: serve over stdin/stdout.
# Anything else is exec'd as-is (debugging).
set -e
case "${1:-http}" in
  http)  [ $# -gt 0 ] && shift; exec vgi-trajectory-worker --http --host 0.0.0.0 --http-threads "${HTTP_THREADS:-2}" --log-format json --port "${PORT:-8000}" "$@" ;;
  stdio) shift; exec vgi-trajectory-worker "$@" ;;
  *)     exec "$@" ;;
esac
