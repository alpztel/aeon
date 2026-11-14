#!/usr/bin/env bash
# One-time setup of an Ubuntu 24.04 droplet for api.a-eon.engineer. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/alpztel/aeon/main/deploy/scripts/bootstrap-droplet.sh | bash -s -- you@example.com
# Prerequisite: an A record api.a-eon.engineer -> this droplet's IP.
set -euo pipefail
EMAIL="${1:?usage: bootstrap-droplet.sh <letsencrypt-email>}"
DOMAIN=api.a-eon.engineer
DIR=/opt/aeon

apt-get update -y
apt-get install -y ca-certificates curl git ufw
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

if [ ! -d "$DIR/.git" ]; then git clone https://github.com/alpztel/aeon.git "$DIR"; fi
cd "$DIR" && git pull --ff-only
touch deploy/.env   # secrets for ai-engine / multi-mission-api go here (never commit)

COMPOSE="docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml"
# First certificate: serve the ACME challenge with a temporary HTTP-only nginx.
docker run -d --rm --name aeon-acme -p 80:80   -v aeon-certbot-www:/var/www/certbot   -v "$DIR/deploy/scripts/acme-only.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine
docker run --rm -v aeon-certbot-www:/var/www/certbot -v aeon-certbot-certs:/etc/letsencrypt   certbot/certbot:v2.11.0 certonly --webroot -w /var/www/certbot   -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
docker rm -f aeon-acme >/dev/null 2>&1 || true

$COMPOSE up -d --build
echo "Deployed: https://$DOMAIN/api/v1/health"
