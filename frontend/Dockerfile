# Production build: a real static build served by nginx, which reverse-proxies /api and /ws to
# the backend service (nginx.conf) -- the app's own code is unchanged from dev, it still calls
# relative /api and /ws/live paths (vite.config.ts's dev-server proxy does the same job locally).
# For local development with hot reload, use Dockerfile.dev via docker-compose.dev.yml instead.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_KEY=
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
