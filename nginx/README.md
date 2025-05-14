# HTTPS Setup for Investment Alphas Application

This document explains how to set up HTTPS for the application.

## Overview

The setup uses:
- HTTPS/TLS between clients and Nginx
- HTTP between Nginx and the backend service
- Self-signed certificates for development (instructions below)
- Automatic HTTP to HTTPS redirection

## Setting Up SSL Certificates

### For Development (Self-Signed Certificates)

1. Run the provided script to generate self-signed certificates:
   ```
   ./generate-ssl-certs.sh
   ```

2. This will create two files in the `nginx/ssl` directory:
   - `server.crt` - The SSL certificate
   - `server.key` - The private key

3. Start the application:
   ```
   docker-compose up -d
   ```

4. Access the application at `https://localhost`

### For Production

For production use, replace the self-signed certificates with proper SSL certificates from a trusted certificate authority like Let's Encrypt.

1. Obtain proper SSL certificates
2. Place them in the `nginx/ssl` directory as:
   - `server.crt` (or create a symbolic link to your certificate)
   - `server.key` (or create a symbolic link to your private key)

## Browser Warning for Self-Signed Certificates

When using self-signed certificates in development, browsers will show a warning. You'll need to:

1. Click "Advanced" or "Show Details"
2. Click "Proceed to localhost (unsafe)" or similar option

This warning is expected for self-signed certificates and can be ignored in development environments. 