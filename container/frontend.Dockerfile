# te-frontend: the web app, built for a plain Node server (#128, BR-38). Build from the
# repo root:  docker build -f container/frontend.Dockerfile -t te-frontend:dev .
#
# The API's address is not known at build time (it depends on the host the browsers
# use), so the build bakes in a placeholder and container/frontend-entrypoint.sh swaps in
# API_PUBLIC_URL every time the container starts. Same placeholder as the Ubuntu
# bundle (scripts/offline/build_bundle.sh). No API key is built in: browsers sign in
# per user (#96).
# #327: the base image is pinned by digest (the tag alone can move under the same name); Dependabot's docker
# ecosystem proposes the new digest when the tag moves. The tag stays for people and for Dependabot.
FROM node:22-slim@sha256:be979e5523c76fa4d5ca4ebd3099078f220aa47ec39c48ad5b5df9314debd6eb AS build
WORKDIR /src
COPY csv-table-hub-main/package.json csv-table-hub-main/package-lock.json ./
RUN npm ci
COPY csv-table-hub-main/ ./
RUN NITRO_PRESET=node-server VITE_API_BASE=__OFFLINE_API_BASE__ npm run build

FROM node:22-slim@sha256:be979e5523c76fa4d5ca4ebd3099078f220aa47ec39c48ad5b5df9314debd6eb
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    NITRO_HOST=0.0.0.0 \
    PORT=8080 \
    NITRO_PORT=8080
COPY --from=build /src/.output /opt/te-frontend
COPY container/frontend-entrypoint.sh /usr/local/bin/frontend-entrypoint.sh
RUN chmod 0755 /usr/local/bin/frontend-entrypoint.sh
# The server starts with `node` alone. npm ships in the node image for building, with its own
# bundled copies of packages (brace-expansion, picomatch, ...) that the image scan flags (#326).
# This stage never runs it, so it is removed rather than carried.
RUN rm -rf /usr/local/lib/node_modules/npm \
 && rm -f /usr/local/bin/npm /usr/local/bin/npx
USER node
EXPOSE 8080
# #327: the same check as the frontend service in docker-compose.yml (the page container/smoke_test.py checks).
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD node -e "fetch('http://localhost:8080/').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"
ENTRYPOINT ["frontend-entrypoint.sh"]
