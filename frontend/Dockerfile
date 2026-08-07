# Build the PWA, then serve it with nginx (which also proxies /api to the backend).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# nginx-unprivileged: runs as uid 101 and listens on 8080 rather than 80.
# The NPM proxy host must target muendlich-web:8080.
FROM nginxinc/nginx-unprivileged:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
