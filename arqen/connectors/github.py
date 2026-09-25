"""GitHub via a personal access token."""

from __future__ import annotations

from arqen.connectors.base import Connector, CredentialField
from arqen.connectors.http import ServiceError, request_json

API = "https://api.github.com"


def github(method: str, path: str, token: str, body: dict | None = None):
    return request_json(method, f"{API}{path}", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, body=body)


def _test(credentials: dict[str, str]) -> str:
    user = github("GET", "/user", credentials["token"])
    login = (user or {}).get("login")
    if not login:
        raise ServiceError("GitHub did not return a user for this token.")
    return login


CONNECTOR = Connector(
    id="github",
    name="GitHub",
    category="Utveckling",
    description="Repon, issues och pull requests. Att skapa issues kräver godkännande.",
    tools=("github_list_repos", "github_list_issues", "github_read_issue",
           "github_list_pull_requests", "github_create_issue"),
    auth="token",
    builtin=False,
    icon="G",
    fields=(CredentialField(
        "token", "Personlig token",
        placeholder="github_pat_…",
        help="Skapa en fine-grained token under GitHub → Settings → Developer settings. "
             "Ge bara läsrätt till repon och issues, plus skrivrätt till issues om agenter ska kunna skapa dem.",
    ),),
    test=_test,
    help_url="https://github.com/settings/personal-access-tokens",
)
