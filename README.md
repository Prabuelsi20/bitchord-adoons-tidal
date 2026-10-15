# TIDAL-only BitChord addon (starter implementation)

This project uses TIDAL's documented OAuth authorization-code + PKCE flow. It does **not** invent a pairing-code endpoint. TIDAL's official developer documentation describes OAuth authorization-code and refresh-token flows; a HiBy-style device code is not assumed.

## Important current limitation

The current official OAuth/catalog API access does not, by itself, prove that a third-party app can obtain a directly playable Hi-Res stream URL. This implementation intentionally returns HTTP 501 from `/stream/{id}` until an authorized, supported playback API/SDK route is established. It does not decrypt or bypass DRM, spoof quality metadata, or return fake stream URLs. Therefore this is **not yet a finished streaming addon** and BitChord playback is not ready.

## Deploy (Ubuntu 24.04 + Docker Compose)

1. Register an application at the [TIDAL Developer Portal](https://developer.tidal.com/) and configure a redirect URI exactly matching `https://YOUR_DOMAIN/auth/callback`.
2. Copy `.env.example` to `.env`, set `TIDAL_CLIENT_ID`, `TIDAL_REDIRECT_URI`, `PUBLIC_BASE_URL`, and region `ID`.
3. Make sure reverse proxy HTTPS routes to container port 8100. Compose binds host `127.0.0.1:8101` by default.
4. Run `docker compose up -d --build`.
5. Open `https://YOUR_DOMAIN/`, click **Connect TIDAL**, and finish login on TIDAL's own page.
6. Check `/health` and `/api/test`.

Persistent tokens are stored in the named Docker volume at `/data/tidal_tokens.json` with restrictive file permissions. Do not publish `.env` or the volume. Never paste access/refresh tokens into support messages.

## Routes

- `GET /` dashboard
- `GET /health` health/status
- `GET /manifest.json` BitChord manifest
- `GET /auth/start` starts OAuth PKCE
- `GET /auth/callback` exchanges the returned code
- `POST /auth/disconnect` removes locally stored tokens
- `GET /api/status`, `GET /api/test`
- `GET /search?q=...` catalog search attempt (depends on the TIDAL app's API access)
- `GET /stream/{id}` deliberately returns 501 until a supported playable-stream path is verified

## Troubleshooting

- OAuth redirect error: registered redirect URI and `TIDAL_REDIRECT_URI` must match byte-for-byte, including scheme and path.
- OAuth config error: verify the app exists and `TIDAL_CLIENT_ID` is set. A developer app is required; don't reuse unknown/private credentials.
- API 401: disconnect and reconnect; the refresh token may be revoked or the app configuration changed.
- Search error: check `docker compose logs --tail=100 tidal-addon` and the app's granted API access/region.
- Playback 501 is intentional, not a transient error: do not point to this addon expecting playback until a supported TIDAL playback integration is implemented and tested.
