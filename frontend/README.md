# Frontend

## Purpose

This frontend is a React + Vite single-page app for the temporary PDF chat backend.

## Main Flow

1. Sign up or log in with email and password.
2. Load the current user and active session.
3. If no session exists, upload one PDF.
4. Wait for live ingestion updates.
5. Ask grounded questions once the session is ready.

## Local Development

1. Copy `.env.example` to `.env` if you want a custom backend URL.
2. Install dependencies.
3. Run the Vite dev server.

Expected environment variable:

- `VITE_API_BASE_URL`

Default backend target:

- `http://127.0.0.1:8000`

For the EC2 deployment path, point `VITE_API_BASE_URL` at the public backend URL for the EC2 stack, for example:

- `http://<ec2-public-ip>:8000`
