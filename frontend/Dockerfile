# =============================================================================
# Stage 1 — builder
# Build the React/Vite SPA into static assets.
# =============================================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package manifests first — layer cache is invalidated only when
# dependencies change, not when source code changes.
COPY package.json package-lock.json* ./

# Install exact versions from lockfile; fail if lockfile is out of date
RUN npm ci

# Copy application source and configuration files
COPY . .

# Produce optimised production build (output: /app/dist)
RUN npm run build

# =============================================================================
# Stage 2 — production
# Serve static assets via NGINX with SPA-aware routing.
# =============================================================================
FROM nginx:1.27-alpine AS production

# Remove the default NGINX configuration
RUN rm /etc/nginx/conf.d/default.conf

# Custom NGINX configuration for Single-Page Application routing
# (try_files falls back to index.html so client-side routes resolve correctly)
COPY --from=builder /app/dist /usr/share/nginx/html

# Inline SPA-routing nginx config so the image is self-contained
RUN cat > /etc/nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Gzip compression for text assets
    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml application/xml+rss text/javascript
               application/vnd.ms-fontobject application/x-font-ttf
               font/opentype image/svg+xml image/x-icon;
    gzip_min_length 1024;
    gzip_vary on;

    # Long-lived cache for hashed static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # SPA fallback: all routes return index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Disable access logs for health-check noise reduction
    location = /favicon.ico { access_log off; log_not_found off; }
    location = /robots.txt  { access_log off; log_not_found off; }
}
EOF

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1
