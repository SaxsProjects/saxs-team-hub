#!/usr/bin/env bash
# The product has one version: /VERSION, the API (backend/app/version.py) and the web app
# (frontend/package.json) and the Android app (mobile/package.json) must agree. With a tag argument (v1.2.3) the tag must match too.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
want="$(tr -d '[:space:]' < "$root/VERSION")"
api="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$root/backend/app/version.py")"
web="$(grep -m1 '"version"' "$root/frontend/package.json" | cut -d'"' -f4)"
android="$(grep -m1 '"version"' "$root/mobile/package.json" | cut -d'"' -f4)"
status=0
for pair in "API:$api" "web app:$web" "Android app:$android"; do
  if [ "${pair#*:}" != "$want" ]; then echo "::error::${pair%%:*} version ${pair#*:} does not match VERSION $want"; status=1; fi
done
if [ $# -gt 0 ] && [ "$1" != "v$want" ]; then echo "::error::tag $1 does not match VERSION $want"; status=1; fi
[ $status -eq 0 ] && echo "All versions are $want"
exit $status
