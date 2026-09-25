from typing import Any

from arqen.connectors.github import github
from arqen.tools.base import Tool

_REPO_HELP = "Repository as owner/name, e.g. stefansemb/Arqen-Desktop."


def _repo(arguments: dict[str, Any]) -> str:
    repo = str(arguments["repo"]).strip().strip("/")
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise ValueError(f"Use owner/name for the repository, got: {repo}")
    return repo


def _clip(text: str | None, limit: int = 1500) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _GitHubTool(Tool):
    connector_id = "github"

    def _get(self, path: str):
        return github("GET", path, self.credentials()["token"])


class GitHubListReposTool(_GitHubTool):
    name = "github_list_repos"
    description = "Lists the connected GitHub user's repositories, most recently updated first."
    arguments_schema = {}

    def run(self, arguments: dict[str, Any]) -> str:
        repos = self._get("/user/repos?sort=updated&per_page=30") or []
        if not repos:
            return "No repositories."
        return "\n".join(
            f"{repo['full_name']}{' (private)' if repo.get('private') else ''} — {repo.get('description') or 'no description'}"
            for repo in repos
        )


class GitHubListIssuesTool(_GitHubTool):
    name = "github_list_issues"
    description = f"Lists open issues in a GitHub repository (pull requests excluded). {_REPO_HELP}"
    arguments_schema = {"repo": str}

    def run(self, arguments: dict[str, Any]) -> str:
        items = [item for item in (self._get(f"/repos/{_repo(arguments)}/issues?state=open&per_page=30") or [])
                 if "pull_request" not in item]
        if not items:
            return "No open issues."
        return "\n".join(f"#{item['number']} {item['title']} ({item['user']['login']})" for item in items)


class GitHubReadIssueTool(_GitHubTool):
    name = "github_read_issue"
    description = f"Reads one GitHub issue: title, state, labels and text. {_REPO_HELP}"
    arguments_schema = {"repo": str, "number": int}

    def normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # Models often send the issue number as text ("12").
        number = arguments.get("number")
        if isinstance(number, str) and number.strip().lstrip("#").isdigit():
            return {**arguments, "number": int(number.strip().lstrip("#"))}
        return arguments

    def run(self, arguments: dict[str, Any]) -> str:
        issue = self._get(f"/repos/{_repo(arguments)}/issues/{int(arguments['number'])}") or {}
        labels = ", ".join(label["name"] for label in issue.get("labels", [])) or "none"
        return (
            f"#{issue.get('number')} {issue.get('title')}\n"
            f"State: {issue.get('state')} · Labels: {labels} · Comments: {issue.get('comments', 0)}\n\n"
            f"{_clip(issue.get('body'))}"
        )


class GitHubListPullRequestsTool(_GitHubTool):
    name = "github_list_pull_requests"
    description = f"Lists open pull requests in a GitHub repository. {_REPO_HELP}"
    arguments_schema = {"repo": str}

    def run(self, arguments: dict[str, Any]) -> str:
        pulls = self._get(f"/repos/{_repo(arguments)}/pulls?state=open&per_page=30") or []
        if not pulls:
            return "No open pull requests."
        return "\n".join(
            f"#{pull['number']} {pull['title']} ({pull['user']['login']}, {pull['head']['ref']} → {pull['base']['ref']})"
            for pull in pulls
        )


class GitHubCreateIssueTool(_GitHubTool):
    name = "github_create_issue"
    description = f"Creates a new issue in a GitHub repository. {_REPO_HELP}"
    requires_confirmation = True
    arguments_schema = {"repo": str, "title": str, "body": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        try:
            _repo(arguments)
        except ValueError as exc:
            return str(exc)
        return None if str(arguments["title"]).strip() else "The issue needs a title."

    def run(self, arguments: dict[str, Any]) -> str:
        issue = github("POST", f"/repos/{_repo(arguments)}/issues", self.credentials()["token"],
                       body={"title": str(arguments["title"]).strip(), "body": str(arguments["body"])}) or {}
        return f"Created issue #{issue.get('number')}: {issue.get('html_url')}"
