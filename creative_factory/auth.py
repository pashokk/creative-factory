"""Google sign-in (OAuth authorization-code flow), restricted to one email domain."""

import json
import os
import secrets
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class AuthError(Exception):
    pass


class GoogleAuth:
    def __init__(self, client_id: str, client_secret: str, base_url: str, domain: str):
        self.client_id, self.client_secret = client_id, client_secret
        self.redirect_uri = base_url.rstrip("/") + "/auth/callback"
        self.domain = domain.lower()

    @classmethod
    def from_env(cls) -> "GoogleAuth | None":
        cid, secret = os.environ.get("GOOGLE_OAUTH_CLIENT_ID"), os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        if not (cid and secret):
            return None
        return cls(cid, secret, os.environ["BASE_URL"], os.environ.get("ALLOWED_DOMAIN", "appodeal.com"))

    def login_url(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": "openid email", "state": state, "prompt": "select_account", "hd": self.domain})
        return f"{AUTH_URL}?{query}", state

    def email_for_code(self, code: str) -> str:
        body = urllib.parse.urlencode({
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, body), timeout=20) as r:
                id_token = json.load(r)["id_token"]
            # tokeninfo verifies the signature and expiry for us
            with urllib.request.urlopen(f"{TOKENINFO_URL}?id_token={urllib.parse.quote(id_token)}", timeout=20) as r:
                info = json.load(r)
        except Exception as e:
            raise AuthError("Google sign-in failed") from e
        return self.check_claims(info)

    def check_claims(self, info: dict) -> str:
        email = (info.get("email") or "").lower()
        if info.get("aud") != self.client_id:
            raise AuthError("token was issued for another app")
        if str(info.get("email_verified")).lower() != "true":
            raise AuthError("email is not verified")
        if not email.endswith("@" + self.domain) or info.get("hd", "").lower() != self.domain:
            raise AuthError(f"only @{self.domain} accounts may sign in")
        return email
