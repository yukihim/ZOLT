# ──────────────────────────────────────────────────────────
# ZOLT Frontend — Multi-stage Dockerfile
# Stage 1: Build React app
# Stage 2: Serve with Nginx
# ──────────────────────────────────────────────────────────

FROM node:20-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install --silent
COPY . .
RUN npm run build

# ── Production stage ──────────────────────────────────────

FROM nginx:alpine AS production

# Custom nginx config for SPA routing
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
    location /api { \
        proxy_pass http://backend:8000; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; \
        \
        # SSE Support \
        proxy_http_version 1.1; \
        proxy_set_header Connection ""; \
        proxy_buffering off; \
        proxy_cache off; \
        chunked_transfer_encoding on; \
        proxy_read_timeout 3600s; \
    } \
}' > /etc/nginx/conf.d/default.conf

COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
