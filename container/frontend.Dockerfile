# te-frontend: the web app, built for a plain Node server (#128, BR-38). Build from the
# repo root:  docker build -f container/frontend.Dockerfile -t te-frontend:dev .
#
# The API's address is not known at build time (it depends on the host the browsers
# use), so the build bakes in a placeholder and container/frontend-entrypoint.sh swaps in
# API_PUBLIC_URL every time the container starts. Same placeholder as the Ubuntu
# bundle (scripts/offline/build_bundle.sh). No API key is built in: browsers sign in
# per user (#96).
FROM node:22-slim AS build
WORKDIR /src
COPY csv-table-hub-main/package.json csv-table-hub-main/package-lock.json ./
RUN npm ci
COPY csv-table-hub-main/ ./
RUN NITRO_PRESET=node-server VITE_API_BASE=__OFFLINE_API_BASE__ npm run build

FROM node:22-slim
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    NITRO_HOST=0.0.0.0 \
    PORT=8080 \
    NITRO_PORT=8080
COPY --from=build /src/.output /opt/te-frontend
COPY container/frontend-entrypoint.sh /usr/local/bin/frontend-entrypoint.sh
RUN chmod 0755 /usr/local/bin/frontend-entrypoint.sh
USER node
EXPOSE 8080
ENTRYPOINT ["frontend-entrypoint.sh"]
