#!/bin/bash
set -e
# Create the ssl directory if it doesn't exist
mkdir -p ssl
# Generate a self-signed certificate for development
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/server.key -out ssl/server.crt \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost" \
  -addext "subjectAltName = DNS:localhost,IP:127.0.0.1"
# Set proper permissions
chmod 600 ssl/server.key
chmod 644 ssl/server.crt
echo "Self-signed SSL certificates generated successfully."
echo "Place them in the nginx/ssl directory before starting the containers."
echo "Note: These certificates are for development only. Use proper certificates for production." 