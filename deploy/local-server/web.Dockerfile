FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/src ./src
COPY frontend/public ./public
COPY frontend/index.html frontend/vite.config.js ./
RUN npm run build
FROM caddy:2-alpine
COPY --from=frontend /app/dist /srv
COPY deploy/local-server/Caddyfile /etc/caddy/Caddyfile
