from __future__ import annotations
import base64, hashlib, html, json, os, secrets, time
from pathlib import Path
from urllib.parse import urlencode, quote
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

APP_VERSION = "0.1.0"
CLIENT_ID = os.getenv("TIDAL_CLIENT_ID", "").strip()
REDIRECT_URI = os.getenv("TIDAL_REDIRECT_URI", "").strip()
COUNTRY = os.getenv("TIDAL_COUNTRY_CODE", "ID").strip().upper()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8101").rstrip("/")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
TOKEN_PATH = DATA_DIR / "tidal_tokens.json"
PENDING_PATH = DATA_DIR / "oauth_pending.json"
AUTH_URL = "https://login.tidal.com/authorize"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
API_BASE = "https://openapi.tidal.com/v2"
SCOPES = ""
app = FastAPI(title="TIDAL-only BitChord Addon", version=APP_VERSION)


def read_json(path: Path, default=None):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return default

def write_json(path: Path, obj):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)

def tokens(): return read_json(TOKEN_PATH, {}) or {}
def connected(): return bool(tokens().get("access_token"))

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

async def refresh_if_needed() -> dict:
    t = tokens()
    if not t.get("access_token"):
        raise HTTPException(401, "TIDAL belum terhubung. Buka dashboard lalu pilih Connect TIDAL.")
    if int(t.get("expires_at", 0)) > int(time.time()) + 60:
        return t
    if not t.get("refresh_token"):
        raise HTTPException(401, "Access token kedaluwarsa dan refresh token tidak tersedia. Hubungkan ulang TIDAL.")
    data = {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": CLIENT_ID}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(TOKEN_URL, data=data)
    if r.is_error:
        raise HTTPException(401, "Refresh token TIDAL ditolak. Silakan Connect TIDAL kembali.")
    payload = r.json()
    t.update(payload)
    t["expires_at"] = int(time.time()) + int(payload.get("expires_in", 0))
    write_json(TOKEN_PATH, t)
    return t

async def tidal_get(path: str, params: dict | None = None):
    t = await refresh_if_needed()
    headers = {"Authorization": f"Bearer {t['access_token']}", "accept": "application/vnd.api+json"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{API_BASE}/{path.lstrip('/')}", headers=headers, params=params or {})
    if r.status_code == 401:
        raise HTTPException(401, "TIDAL menolak token. Coba Disconnect lalu Connect TIDAL lagi.")
    if r.is_error:
        raise HTTPException(502, f"TIDAL API gagal dengan HTTP {r.status_code}; periksa akses aplikasi dan region.")
    return r.json()

@app.get("/health")
async def health():
    t = tokens()
    return {"status":"ok", "provider":"TIDAL", "version":APP_VERSION,
            "oauth_connected":connected(), "token_expires_at":t.get("expires_at"),
            "playback_ready":False,
            "note":"OAuth/catalog scaffold; official playable-stream capability is not confirmed by this service."}

@app.get("/manifest.json")
async def manifest():
    return {"id":"id.ngaberssmp.tidal-only", "name":"TIDAL Only (Self-hosted)", "version":APP_VERSION,
            "description":"TIDAL catalogue addon; stream resolution is enabled only when a supported authorized playback URL is available.",
            "resources":["search","stream"], "types":["track","album","artist"], "allowDownloads":0,
            "settings":[{"key":"quality","type":"select","default":"lossless","options":[{"label":"Hi-Res Lossless (when available)","value":"hi_res"},{"label":"Lossless", "value":"lossless"}]}]}

@app.get("/auth/start")
async def auth_start():
    if not CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(503, "Isi TIDAL_CLIENT_ID dan TIDAL_REDIRECT_URI di .env dari aplikasi TIDAL Developer yang terdaftar.")
    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(32)
    write_json(PENDING_PATH, {"verifier":verifier,"state":state,"created_at":int(time.time())})
    params = {"response_type":"code","client_id":CLIENT_ID,"redirect_uri":REDIRECT_URI,
              "code_challenge_method":"S256","code_challenge":challenge,"state":state}
    if SCOPES: params["scope"] = SCOPES
    return RedirectResponse(AUTH_URL + "?" + urlencode(params), status_code=302)

@app.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error: return HTMLResponse(f"<h2>TIDAL login gagal</h2><p>{html.escape(error)}</p><a href='/'>Kembali</a>", status_code=400)
    pending = read_json(PENDING_PATH, {}) or {}
    if not code or not state or not secrets.compare_digest(state, pending.get("state", "")) or int(time.time()) - int(pending.get("created_at", 0)) > 600:
        raise HTTPException(400, "OAuth state tidak cocok atau sesi kedaluwarsa. Mulai Connect TIDAL lagi.")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(TOKEN_URL, data={"grant_type":"authorization_code","client_id":CLIENT_ID,"code":code,"redirect_uri":REDIRECT_URI,"code_verifier":pending["verifier"]})
    if r.is_error:
        return HTMLResponse("<h2>Token exchange gagal</h2><p>Periksa Client ID, redirect URI yang terdaftar, dan log server (respons rahasia tidak dicatat).</p><a href='/'>Kembali</a>", status_code=502)
    payload = r.json(); payload["expires_at"] = int(time.time()) + int(payload.get("expires_in", 0))
    write_json(TOKEN_PATH, payload)
    try: PENDING_PATH.unlink()
    except OSError: pass
    return RedirectResponse("/?connected=1", status_code=303)

@app.post("/auth/disconnect")
async def auth_disconnect():
    try: TOKEN_PATH.unlink()
    except FileNotFoundError: pass
    return {"ok":True,"connected":False}

@app.get("/api/status")
async def api_status():
    t = tokens()
    return {"provider":"TIDAL","connected":connected(),"expires_at":t.get("expires_at"),"version":APP_VERSION,"playback_ready":False}

@app.get("/api/test")
async def test_connection():
    # Verify a user token against the official API, without returning credentials.
    try:
        await tidal_get("genres", {"countryCode":COUNTRY,"page[limit]":1})
        return {"ok":True,"message":"Token diterima oleh TIDAL API."}
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok":False,"message":str(e.detail)})

@app.get("/search")
async def search(q: str = "", limit: int = 20):
    if not q.strip(): return {"tracks":[]}
    # TIDAL public API search is versioned; preserve provider errors instead of fabricating results.
    data = await tidal_get(f"searchResults/{quote(q.strip(), safe='')}", {"countryCode":COUNTRY,"include":"tracks","page[limit]":max(1,min(limit,50))})
    tracks = []
    for item in data.get("included", []):
        if item.get("type") != "tracks": continue
        a = item.get("attributes", {})
        rel = item.get("relationships", {})
        tracks.append({"id":f"td:{item.get('id')}","title":a.get("title",""),"artist":"", "album":"",
                       "duration":a.get("duration"),"artworkURL":None,"audioQuality":a.get("audioQuality")})
    return {"tracks":tracks}

@app.get("/stream/{track_id}")
async def stream(track_id: str, quality: str = "lossless"):
    # Do not fabricate a media URL or claim Hi-Res based on catalogue metadata.
    raise HTTPException(501, "Playback belum tersedia: public TIDAL API OAuth/catalog tidak dengan sendirinya memberikan URL audio yang dapat diputar. Endpoint ini sengaja tidak mengembalikan URL palsu atau melewati proteksi akses.")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    status = "Connected" if connected() else "Not connected"
    expires = tokens().get("expires_at")
    exp_text = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(expires)) if expires else "—"
    return HTMLResponse(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TIDAL Only · BitChord</title>
<style>body{{font:16px system-ui;background:#0b0d12;color:#edf0f7;margin:0;padding:24px}}main{{max-width:760px;margin:auto}}.card{{background:#151923;border:1px solid #2a3040;border-radius:16px;padding:22px;margin:14px 0}}button,a.btn{{background:#e6ff3f;color:#111;padding:11px 16px;border:0;border-radius:9px;font-weight:700;text-decoration:none;cursor:pointer;display:inline-block}}.muted{{color:#a7b0c4}}.warn{{color:#ffd18a}}code{{overflow-wrap:anywhere}}</style>
<main><h1>TIDAL Only <span class="muted">/ BitChord</span></h1><p class="muted">Self-hosted addon · v{APP_VERSION}</p><section class="card"><h2>Account</h2><p>Status: <b>{status}</b></p><p class="muted">Token expiry: {exp_text}</p><a class="btn" href="/auth/start">Connect TIDAL</a> <button onclick="disconnect()">Disconnect</button> <button onclick="test()">Test connection</button><p id="msg" class="muted"></p></section>
<section class="card"><h2>BitChord endpoint</h2><p>Add this addon URL to BitChord:</p><code>{html.escape(PUBLIC_BASE_URL)}</code><p><a href="/manifest.json">Open manifest.json</a> · <a href="/health">Health</a></p></section>
<section class="card"><h2>Playback status</h2><p class="warn">Not ready</p><p>OAuth does not automatically grant a playable audio URL. The official API playback entitlement/SDK path must be confirmed before this addon can truthfully advertise working playback. Search/stream routes are not being faked.</p></section>
<section class="card"><h2>Setup requirement</h2><p class="muted">Register an app in the official TIDAL Developer Portal, then set <code>TIDAL_CLIENT_ID</code> and the exact registered <code>TIDAL_REDIRECT_URI</code> in .env. The redirect URI must point to this service's <code>/auth/callback</code>.</p></section></main>
<script>async function disconnect(){{let r=await fetch('/auth/disconnect',{{method:'POST'}});document.getElementById('msg').textContent=r.ok?'Disconnected. Reload the page.':'Disconnect failed';}}async function test(){{let r=await fetch('/api/test');let j=await r.json();document.getElementById('msg').textContent=j.message||JSON.stringify(j);}}</script></html>''')
