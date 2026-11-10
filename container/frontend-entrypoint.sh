#!/bin/sh
# Start the frontend with the API address filled in (#128). The image holds a pristine
# copy of the build; each start copies it and substitutes the placeholder, so changing
# API_PUBLIC_URL and restarting works (a one-time sed on the image would not).
set -eu

: "${API_PUBLIC_URL:?API_PUBLIC_URL is required, e.g. http://localhost:8000}"
# It goes into a sed replacement and into JavaScript: allow only what a URL needs.
case "$API_PUBLIC_URL" in
  http://*|https://*) ;;
  *) echo "API_PUBLIC_URL must start with http:// or https://" >&2; exit 1 ;;
esac
case "$API_PUBLIC_URL" in
  *[!A-Za-z0-9:/._-]*) echo "API_PUBLIC_URL may contain only letters, digits and : / . _ -" >&2; exit 1 ;;
esac

rm -rf /tmp/app
cp -r /opt/te-frontend /tmp/app
grep -rl "__OFFLINE_API_BASE__" /tmp/app | xargs -r sed -i "s#__OFFLINE_API_BASE__#${API_PUBLIC_URL%/}#g"
exec node /tmp/app/server/index.mjs
