# PWA image: builds the static app and serves it with NGINX, proxying /api/ to the API.
# Build context: frontend/. Used by .github/workflows/deploy.yml.
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
# The official image renders /etc/nginx/templates/*.template with envsubst at start-up.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Host (or host:port) of the API, e.g. 10.100.0.5:8000. Set it in the environment.
ENV API_UPSTREAM=api:8000
EXPOSE 80
