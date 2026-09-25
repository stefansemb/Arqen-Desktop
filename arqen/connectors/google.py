"""Google (Gmail, Calendar, Drive) via OAuth for desktop apps.

The user creates their own OAuth client of the type "Desktop app" in Google
Cloud and types its ID and secret in.  Signing in opens the browser at Google;
the answer comes back to a short-lived listener on 127.0.0.1 and is exchanged
with PKCE, so the code is useless to anyone who intercepts it.  Only the
refresh token is kept (in ``arqen-secrets.json``); access tokens live in memory
for their hour and are fetched again when they run out.

A desktop client's "secret" is not really secret (Google says as much), but it
is stored and scrubbed like the rest so it never reaches the model.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from arqen.connectors.base import Connector, CredentialField
from arqen.connectors.http import ServiceError, request_bytes, request_json

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"

# The least each tool needs.  Gmail has no scope for drafts alone; compose
# allows drafts (and sending, which Arqen has no tool for).
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
)
SIGN_IN_TIMEOUT = 300

REAUTHORIZE = "The Google sign-in has expired or was revoked. Sign in again under Anslutningar → Google."


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _page(title: str, text: str) -> bytes:
    return (
        "<!doctype html><meta charset='utf-8'><title>Arqen</title>"
        "<body style='font-family:sans-serif;background:#111516;color:#f2f0eb;padding:48px'>"
        f"<h2 style='color:#b7ff18'>{title}</h2><p>{text}</p></body>"
    ).encode("utf-8")


def _wait_for_code(server: HTTPServer, state: str, cancel: threading.Event, timeout: float) -> str:
    """Serve the loopback address until Google redirects back with a code."""
    from arqen.ui.strings import tr

    answer: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - name set by http.server
            query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
            if "code" not in query and "error" not in query:
                self.send_response(404)  # e.g. the browser asking for a favicon
                self.end_headers()
                return
            if query.get("state") != state:
                answer["error"] = "state_mismatch"
            elif "error" in query:
                answer["error"] = query["error"]
            else:
                answer["code"] = query["code"]
            ok = "code" in answer
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_page(
                tr("Arqen is connected to Google") if ok else tr("The sign-in did not go through"),
                tr("You can close this tab and go back to Arqen.") if ok else tr("Go back to Arqen and try again."),
            ))

        def log_message(self, *args) -> None:
            pass  # the request line carries the code; keep it off the console

    server.RequestHandlerClass = Handler
    server.timeout = 0.5
    deadline = time.monotonic() + timeout
    while not answer:
        if cancel.is_set():
            raise ServiceError("The sign-in was cancelled.")
        if time.monotonic() > deadline:
            raise ServiceError("No answer from Google in time. Try again.")
        server.handle_request()
    if "error" in answer:
        if answer["error"] == "access_denied":
            raise ServiceError("Access was not granted in Google.")
        raise ServiceError(f"Google did not sign in ({answer['error']}).")
    return answer["code"]


def authorize(credentials: dict[str, str], cancel: threading.Event | None = None,
              open_url: Callable[[str], object] = webbrowser.open, timeout: float = SIGN_IN_TIMEOUT) -> dict:
    """Run the browser sign-in; returns the refresh token and account details."""
    client_id, client_secret = credentials["client_id"].strip(), credentials["client_secret"].strip()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    # Port 0: the system picks a free one.  Google accepts any port on the
    # loopback address for desktop clients.
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        open_url(AUTH_URL + "?" + urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            # Always ask, so Google always hands out a refresh token.
            "prompt": "consent",
        }))
        code = _wait_for_code(server, state, cancel or threading.Event(), timeout)
    finally:
        server.server_close()
    tokens = request_json("POST", TOKEN_URL, form={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }) or {}
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise ServiceError("Google did not hand out a refresh token.")
    _remember(refresh, tokens)
    granted = tuple(scope for scope in SCOPES if scope in str(tokens.get("scope", "")).split())
    account = ""
    if SCOPES[0] in granted:
        account = str((_api("GET", f"{GMAIL}/profile", tokens["access_token"]) or {}).get("emailAddress", ""))
    return {
        "refresh_token": refresh,
        "settings": {"account": account, "scopes": list(granted), "needs_reconnect": False},
        # Google lets the user untick scopes on the consent page.
        "missing": missing_scopes(granted),
    }


def missing_scopes(granted) -> list[str]:
    """Short names of the scopes the user left unticked in Google's consent."""
    return [scope.rsplit("/", 1)[-1] for scope in SCOPES if scope not in (granted or ())]


# refresh token -> (access token, monotonic expiry).  Kept in memory only.
_ACCESS: dict[str, tuple[str, float]] = {}
_ACCESS_LOCK = threading.Lock()


def _remember(refresh: str, tokens: dict) -> None:
    if tokens.get("access_token"):
        with _ACCESS_LOCK:
            _ACCESS[refresh] = (tokens["access_token"], time.monotonic() + float(tokens.get("expires_in", 3600)))


def access_token(credentials: dict[str, str]) -> str:
    """A valid access token, refreshed when the cached one is about to run out."""
    refresh = credentials.get("refresh_token", "").strip()
    if not refresh:
        raise ServiceError("Google is not signed in. Sign in under Anslutningar → Google.")
    with _ACCESS_LOCK:
        cached = _ACCESS.get(refresh)
    if cached and cached[1] - time.monotonic() > 60:
        return cached[0]
    try:
        tokens = request_json("POST", TOKEN_URL, form={
            "client_id": credentials.get("client_id", "").strip(),
            "client_secret": credentials.get("client_secret", "").strip(),
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }) or {}
    except ServiceError as exc:
        # Testing-mode clients get refresh tokens that expire after 7 days.
        if "invalid_grant" in str(exc) or "HTTP 401" in str(exc):
            _mark_needs_reconnect(True)
            raise ServiceError(REAUTHORIZE) from None
        raise
    if not tokens.get("access_token"):
        _mark_needs_reconnect(True)
        raise ServiceError(REAUTHORIZE)
    _remember(refresh, tokens)
    _mark_needs_reconnect(False)
    return tokens["access_token"]


def _mark_needs_reconnect(value: bool) -> None:
    """Let the Connections card show that the sign-in has to be renewed."""
    from arqen.connectors.store import load_settings, save_settings

    if bool(load_settings("google").get("needs_reconnect", False)) != value:
        save_settings("google", needs_reconnect=value)


def _api(method: str, url: str, token: str, body: dict | None = None):
    return request_json(method, url, headers={"Authorization": f"Bearer {token}"}, body=body)


def google_json(method: str, url: str, credentials: dict[str, str], body: dict | None = None):
    return _api(method, url, access_token(credentials), body=body)


def google_bytes(url: str, credentials: dict[str, str], max_bytes: int) -> bytes:
    return request_bytes("GET", url, headers={"Authorization": f"Bearer {access_token(credentials)}"},
                         max_bytes=max_bytes)


def revoke(credentials: dict[str, str]) -> None:
    """Tell Google to forget the grant; best effort, disconnecting works regardless."""
    refresh = credentials.get("refresh_token", "").strip()
    if not refresh:
        return
    with _ACCESS_LOCK:
        _ACCESS.pop(refresh, None)
    try:
        request_json("POST", REVOKE_URL, form={"token": refresh})
    except ServiceError:
        pass


def _test(credentials: dict[str, str]) -> str:
    profile = google_json("GET", f"{GMAIL}/profile", credentials) or {}
    if not profile.get("emailAddress"):
        raise ServiceError("Google did not return an account for this sign-in.")
    return profile["emailAddress"]


CONNECTOR = Connector(
    id="google",
    name="Google",
    category="Produktivitet",
    description="Läsa Gmail, Kalender och Drive. Mejlutkast och kalenderhändelser skapas med godkännande; inget skickas.",
    tools=("gmail_search_messages", "gmail_read_message", "gmail_create_draft",
           "calendar_list_events", "calendar_create_event",
           "drive_search_files", "drive_read_file"),
    auth="oauth",
    builtin=False,
    icon="Go",
    fields=(
        CredentialField(
            "client_id", "Klient-ID", secret=False,
            placeholder="…apps.googleusercontent.com",
            help="Google Cloud Console → API:er och tjänster → Inloggningsuppgifter → "
                 "Skapa OAuth-klient-ID av typen Datorapp (Desktop app).",
        ),
        CredentialField("client_secret", "Klienthemlighet", placeholder="GOCSPX-…"),
    ),
    issued=("refresh_token",),
    test=_test,
    sign_in=authorize,
    sign_out=revoke,
    help_url="https://console.cloud.google.com/apis/credentials",
)
