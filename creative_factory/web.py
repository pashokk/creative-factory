"""Web UI and JSON API. Run with: uvicorn creative_factory.web:app --host 0.0.0.0 --port 8000"""

import datetime
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import MISSING, asdict, fields

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import analysis, elevenlabs, naming, qa
from .auth import AuthError, GoogleAuth
from .drive import FOLDER, Drive
from .jobs import JobStore, Worker
from .pipeline import JobSpec, run_job, validate
from .registry import Registry

DRIVE_ROOT_ID = os.environ.get("DRIVE_ROOT_ID", "0AFIgRksacladUk9PVA")
DATA_DIR = os.environ.get("DATA_DIR", "data")
STATIC = os.path.join(os.path.dirname(__file__), "static")
MAX_UPLOAD_MB = 600
KINDS = {"logo": "logo__", "endcard_bg": "endcard_bg__", "footage": "", "other": ""}

auth = GoogleAuth.from_env()
DEV_USER = os.environ.get("DEV_USER")  # local development only: skips Google sign-in
if auth is None and not DEV_USER:
    raise RuntimeError("Set GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET/BASE_URL "
                       "(or DEV_USER for local development only)")
if auth is not None and DEV_USER:
    raise RuntimeError("DEV_USER must not be set together with Google sign-in")

drive = Drive(DRIVE_ROOT_ID)
registry = Registry(os.path.join(DATA_DIR, "registry.json"), scan=drive.scan_games)
store = JobStore(os.path.join(DATA_DIR, "jobs.json"))


def _handler(spec: dict, work: str, say) -> dict:
    known = {f.name for f in fields(JobSpec)}
    return run_job(JobSpec(**{k: v for k, v in spec.items() if k in known}), drive, registry, work, say)


worker = Worker(store, _handler, os.path.join(DATA_DIR, "work"))

app = FastAPI(title="Creative Factory", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
                   https_only=os.environ.get("BASE_URL", "").startswith("https://"), same_site="lax",
                   max_age=12 * 3600)


def current_user(request: Request) -> str:
    user = DEV_USER or request.session.get("user")
    if not user:
        raise HTTPException(401, "sign in required")
    return user


# -- sign-in --------------------------------------------------------------
@app.get("/login")
def login(request: Request):
    if auth is None:
        return RedirectResponse("/")
    url, state = auth.login_url()
    request.session["state"] = state
    return RedirectResponse(url)


@app.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = ""):
    expected = request.session.pop("state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return Response("Sign-in failed (bad state). Go back and try again.", status_code=400)
    try:
        request.session["user"] = auth.email_for_code(code)
    except AuthError as e:
        return Response(str(e), status_code=403)
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/api/me")
def me(request: Request):
    user = DEV_USER or request.session.get("user")
    if not user:
        return JSONResponse({"user": None}, status_code=401)
    return {"user": user}


# -- games and assets -------------------------------------------------------
_cache: dict = {}
_cache_lock = threading.Lock()


def cached(key: str, ttl: float, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def _year() -> str:
    return str(datetime.date.today().year)


def _assets_folder(game_id: str, create: bool, sub: str = "") -> str | None:
    parent = game_id
    for name in (_year(), "Assets", *([sub] if sub else [])):
        if create:
            parent = drive.ensure_folder(parent, name)
        else:
            found = drive.find_child(parent, name, folder=True)
            if not found:
                return None
            parent = found["id"]
    return parent


def _asset(f: dict) -> dict:
    name = f["name"]
    role = "logo" if name.startswith("logo__") else "endcard_bg" if name.startswith("endcard_bg__") else None
    return {"id": f["id"], "name": name, "size": int(f.get("size") or 0), "mime": f["mimeType"], "role": role}


@app.get("/api/games")
def games(user: str = Depends(current_user)):
    folders = cached("games", 120, lambda: drive.children(DRIVE_ROOT_ID, folders_only=True))
    return [{"id": f["id"], "name": f["name"]} for f in folders]


@app.post("/api/games")
def create_game(name: str = Form(...), user: str = Depends(current_user)):
    name = name.strip()
    if not re.fullmatch(r"[^/\\]{2,80}", name):
        raise HTTPException(400, "game name must be 2-80 characters without slashes")
    if drive.find_child(DRIVE_ROOT_ID, name, folder=True):
        raise HTTPException(409, "a game with this name already exists")
    gid = drive.ensure_folder(DRIVE_ROOT_ID, name)
    for sub in ("ASO", "Assets", "Creatives/Videos", "Creatives/Static"):
        drive.ensure_path(gid, _year(), *sub.split("/"))
    _cache.pop("games", None)
    return {"id": gid, "name": name}


@app.get("/api/prefix")
def prefix_preview(game: str, manual: str = "", user: str = Depends(current_user)):
    try:
        manual_prefix = naming.validate_manual_prefix(manual) if manual else None
        prefix, cid = registry.peek(game, manual_prefix)
    except ValueError as e:
        return {"needs_manual": True, "suggestion": naming.suggest_prefix(game), "message": str(e)}
    return {"needs_manual": False, "prefix": prefix, "next_id": f"{prefix}{cid:03d}"}


@app.get("/api/games/{game_id}/assets")
def list_assets(game_id: str, user: str = Depends(current_user)):
    assets = _assets_folder(game_id, create=False)
    footage = _assets_folder(game_id, create=False, sub="Footage")
    return {"assets": [_asset(f) for f in drive.children(assets) if f["mimeType"] != FOLDER] if assets else [],
            "footage": [_asset(f) for f in drive.children(footage) if f["mimeType"] != FOLDER] if footage else []}


@app.post("/api/games/{game_id}/assets")
async def upload_asset(game_id: str, kind: str = Form(...), file: UploadFile = File(...),
                       user: str = Depends(current_user)):
    if kind not in KINDS:
        raise HTTPException(400, "kind must be logo, endcard_bg, footage or other")
    name = re.sub(r"[^\w .()\-\[\]]", "_", os.path.basename(file.filename or "upload"))
    ext = os.path.splitext(name)[1].lower()
    allowed = {".mp4", ".mov"} if kind == "footage" else {".png", ".jpg", ".jpeg", ".webp"} if kind != "other" else None
    if allowed and ext not in allowed:
        raise HTTPException(400, f"{kind} must be one of {', '.join(sorted(allowed))}")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        size = 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                os.unlink(tmp.name)
                raise HTTPException(413, f"file is over {MAX_UPLOAD_MB} MB")
            tmp.write(chunk)
    try:
        parent = _assets_folder(game_id, create=True, sub="Footage" if kind == "footage" else "")
        uploaded = drive.upload(tmp.name, parent, KINDS[kind] + name)
    finally:
        os.unlink(tmp.name)
    return {"id": uploaded["id"], "name": uploaded["name"]}


@app.get("/api/files/{file_id}/image")
def image(file_id: str, user: str = Depends(current_user)):
    meta = drive.metadata(file_id, "id,mimeType,size")
    if not meta["mimeType"].startswith("image/") or int(meta.get("size") or 0) > 15_000_000:
        raise HTTPException(404, "not a previewable image")
    with tempfile.TemporaryDirectory() as d:
        path = drive.download(file_id, os.path.join(d, "img"))
        with open(path, "rb") as f:
            return Response(f.read(), media_type=meta["mimeType"], headers={"Cache-Control": "private, max-age=300"})


# -- voices and jobs ------------------------------------------------------------
@app.get("/api/voices")
def voices(user: str = Depends(current_user)):
    return cached("voices", 3600, elevenlabs.voices)


@app.post("/api/jobs")
def create_job(spec: dict, user: str = Depends(current_user)):
    known = {f.name for f in fields(JobSpec)}
    unknown = set(spec) - known
    if unknown:
        raise HTTPException(400, f"unknown fields: {sorted(unknown)}")
    required = [f.name for f in fields(JobSpec) if f.default is MISSING and f.default_factory is MISSING]
    missing = [name for name in required if not spec.get(name)]
    if missing:
        raise HTTPException(400, f"missing: {', '.join(missing)}")
    parsed = JobSpec(**spec)
    problems = validate(parsed)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    return worker.submit(user, asdict(parsed))


@app.get("/api/jobs")
def list_jobs(user: str = Depends(current_user)):
    return [{k: j[k] for k in ("id", "user", "status", "created", "finished", "error")}
            | {"game": j["spec"].get("game"), "concept": j["spec"].get("concept")} for j in store.recent()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: str = Depends(current_user)):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


# -- AI suggestions (cut, crop, hook, script) ---------------------------------------
_analyses: dict[str, dict] = {}


def _run_analysis(task_id: str, game: str, footage_id: str, brief: str, lang: str) -> None:
    try:
        with tempfile.TemporaryDirectory() as work:
            video = drive.download(footage_id, os.path.join(work, "footage.mp4"))
            duration = qa.probe(video).duration_s
            result = analysis.suggest(video, work, game, brief, duration, lang)
        _analyses[task_id] = {"status": "done", "result": result, "duration": duration}
    except Exception as e:
        _analyses[task_id] = {"status": "failed", "error": str(e) or type(e).__name__}


@app.get("/api/config")
def config(user: str = Depends(current_user)):
    return {"ai": analysis.provider() is not None}


@app.post("/api/analyze")
def analyze(body: dict, user: str = Depends(current_user)):
    if analysis.provider() is None:
        raise HTTPException(400, "AI suggestions are not configured (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
    game, footage_id = str(body.get("game", "")), str(body.get("footage_id", ""))
    if not game or not footage_id:
        raise HTTPException(400, "game and footage_id are required")
    task_id = secrets.token_hex(6)
    _analyses[task_id] = {"status": "running"}
    for old in list(_analyses)[:-50]:  # keep the dict small
        _analyses.pop(old, None)
    threading.Thread(target=_run_analysis, daemon=True, args=(
        task_id, game, footage_id, str(body.get("brief", ""))[:2000], str(body.get("lang", "EN"))[:2])).start()
    return {"id": task_id}


@app.get("/api/analyze/{task_id}")
def analysis_status(task_id: str, user: str = Depends(current_user)):
    task = _analyses.get(task_id)
    if not task:
        raise HTTPException(404, "no such analysis")
    return task


@app.get("/healthz")
def healthz():
    return {"ok": True}


ICONS = {"favicon.ico": "image/x-icon", "favicon-16.png": "image/png", "favicon-32.png": "image/png",
         "apple-touch-icon.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png"}


@app.get("/favicon.ico")
@app.get("/static/{name}")
def icon(name: str = "favicon.ico"):
    if name not in ICONS:
        raise HTTPException(404, "not found")
    return FileResponse(os.path.join(STATIC, name), media_type=ICONS[name],
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
