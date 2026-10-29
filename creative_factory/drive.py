"""Google Drive storage (API v3, service account).

The service account key is GOOGLE_SERVICE_ACCOUNT_B64 (base64 of the key JSON).
Only folders shared with the service account are visible. Everything uses
supportsAllDrives because the root is a shared drive.
"""

import base64
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Optional

from . import naming

FOLDER = "application/vnd.google-apps.folder"
SCOPE = "https://www.googleapis.com/auth/drive"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
CHUNK = 8 * 1024 * 1024  # resumable upload chunk, a multiple of 256 KiB


class DriveError(RuntimeError):
    pass


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


class Drive:
    def __init__(self, root_id: str, key_b64: Optional[str] = None):
        self.root_id = root_id
        self._key = json.loads(base64.b64decode(key_b64 or os.environ["GOOGLE_SERVICE_ACCOUNT_B64"]))
        self._token: Optional[str] = None
        self._expires = 0.0
        self._lock = threading.Lock()

    # -- auth -------------------------------------------------------------
    def _access_token(self) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token
            now = int(time.time())
            head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
            claims = _b64(json.dumps({"iss": self._key["client_email"], "scope": SCOPE,
                                      "aud": self._key["token_uri"], "iat": now, "exp": now + 3600}).encode())
            pem = serialization.load_pem_private_key(self._key["private_key"].encode(), None)
            sig = _b64(pem.sign(head + b"." + claims, padding.PKCS1v15(), hashes.SHA256()))
            body = urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": (head + b"." + claims + b"." + sig).decode()}).encode()
            with urllib.request.urlopen(urllib.request.Request(self._key["token_uri"], body), timeout=30) as r:
                data = json.load(r)
            self._token, self._expires = data["access_token"], now + int(data["expires_in"])
            return self._token

    def _request(self, method: str, url: str, body: Optional[bytes] = None,
                 headers: Optional[dict] = None, retries: int = 4):
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, body, {"Authorization": "Bearer " + self._access_token(),
                                                      **(headers or {})}, method=method)
            try:
                return urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                detail = e.read().decode(errors="replace")[:300]
                raise DriveError(f"Drive {method} {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def _json(self, method: str, path: str, params: Optional[dict] = None, payload: Optional[dict] = None):
        q = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true", **(params or {})}
        url = f"{API}/{path}?{urllib.parse.urlencode(q)}"
        body = json.dumps(payload).encode() if payload is not None else None
        with self._request(method, url, body, {"Content-Type": "application/json"} if body else None) as r:
            return json.load(r)

    # -- queries ----------------------------------------------------------
    def query(self, q: str, fields: str = "id,name,mimeType,size,parents", all_pages: bool = True) -> list[dict]:
        out, token = [], None
        while True:
            params = {"q": q, "fields": f"nextPageToken,files({fields})", "pageSize": "1000",
                      "corpora": "drive", "driveId": self.root_id}
            if token:
                params["pageToken"] = token
            page = self._json("GET", "files", params)
            out += page["files"]
            token = page.get("nextPageToken")
            if not token or not all_pages:
                return out

    def children(self, parent_id: str, folders_only: bool = False) -> list[dict]:
        q = f"'{parent_id}' in parents and trashed=false"
        if folders_only:
            q += f" and mimeType='{FOLDER}'"
        return sorted(self.query(q), key=lambda f: f["name"].casefold())

    def find_child(self, parent_id: str, name: str, folder: Optional[bool] = None) -> Optional[dict]:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"'{parent_id}' in parents and name='{safe}' and trashed=false"
        if folder is not None:
            q += f" and mimeType{'=' if folder else '!='}'{FOLDER}'"
        found = self.query(q, all_pages=False)
        return found[0] if found else None

    def ensure_folder(self, parent_id: str, name: str) -> str:
        existing = self.find_child(parent_id, name, folder=True)
        if existing:
            return existing["id"]
        return self._json("POST", "files", {"fields": "id"},
                          {"name": name, "mimeType": FOLDER, "parents": [parent_id]})["id"]

    def ensure_path(self, parent_id: str, *names: str) -> str:
        for name in names:
            parent_id = self.ensure_folder(parent_id, name)
        return parent_id

    def metadata(self, file_id: str, fields: str = "id,name,mimeType,size,parents,webViewLink") -> dict:
        return self._json("GET", f"files/{file_id}", {"fields": fields})

    # -- transfer ---------------------------------------------------------
    def download(self, file_id: str, dest: str) -> str:
        url = f"{API}/files/{file_id}?alt=media&supportsAllDrives=true"
        tmp = dest + ".part"
        with self._request("GET", url) as r, open(tmp, "wb") as f:
            while chunk := r.read(1024 * 1024):
                f.write(chunk)
        os.replace(tmp, dest)
        return dest

    def upload(self, path: str, parent_id: str, name: Optional[str] = None) -> dict:
        """Resumable upload of a local file; replaces nothing, always creates."""
        name = name or os.path.basename(path)
        size = os.path.getsize(path)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        init_url = (f"{UPLOAD}?uploadType=resumable&supportsAllDrives=true"
                    f"&fields={urllib.parse.quote('id,name,size,webViewLink')}")
        meta = json.dumps({"name": name, "parents": [parent_id]}).encode()
        with self._request("POST", init_url, meta, {
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)}) as r:
            session = r.headers["Location"]
        with open(path, "rb") as f:
            offset = 0
            while True:
                data = f.read(CHUNK)
                end = offset + len(data) - 1
                rng = f"bytes {offset}-{end}/{size}" if size else "bytes */0"
                req = urllib.request.Request(session, data, {"Content-Range": rng}, method="PUT")
                try:
                    with urllib.request.urlopen(req, timeout=300) as r:
                        return json.load(r)  # 200/201: finished
                except urllib.error.HTTPError as e:
                    if e.code != 308:
                        raise DriveError(f"Drive upload {e.code}: {e.read().decode(errors='replace')[:300]}") from None
                offset += len(data)

    def trash(self, file_id: str) -> None:
        self._json("PATCH", f"files/{file_id}", {"fields": "id"}, {"trashed": True})

    # -- registry scan ----------------------------------------------------
    def scan_games(self) -> dict[str, list[str]]:
        """{game folder name: creative filenames below it}, from two bulk queries."""
        folders = {f["id"]: f for f in self.query(f"mimeType='{FOLDER}' and trashed=false", "id,name,parents")}
        files = self.query("mimeType='video/mp4' and trashed=false", "id,name,parents")
        return games_from_listing(self.root_id, folders, files)


def games_from_listing(root_id: str, folders: dict[str, dict], files: Iterable[dict]) -> dict[str, list[str]]:
    """Group mp4 names by the top-level folder (game) they live under."""
    def game_of(parent_id: str) -> Optional[str]:
        seen = set()
        while parent_id in folders and parent_id not in seen:
            seen.add(parent_id)
            up = (folders[parent_id].get("parents") or [None])[0]
            if up == root_id:
                return folders[parent_id]["name"]
            parent_id = up
        return None

    games: dict[str, list[str]] = {}
    for f in files:
        if naming.parse_filename(f["name"]) is None:
            continue
        game = game_of((f.get("parents") or [""])[0])
        if game:
            games.setdefault(game, []).append(f["name"])
    return games
