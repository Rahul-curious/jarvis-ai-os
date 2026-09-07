"""Typed schemas and data models for GitHub integration payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GitHubUserSummary(BaseModel):
    """Normalized summary of a GitHub user or organization."""

    model_config = ConfigDict(frozen=True)

    id: int
    login: str
    type: str = "User"
    html_url: str
    avatar_url: str | None = None
    name: str | None = None


class GitHubRepoSummary(BaseModel):
    """Normalized summary of a GitHub repository."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    full_name: str
    owner: str
    description: str | None = None
    private: bool = False
    html_url: str
    default_branch: str = "main"
    created_at: str | None = None
    updated_at: str | None = None


class GitHubIssueSummary(BaseModel):
    """Normalized summary of a GitHub issue."""

    model_config = ConfigDict(frozen=True)

    id: int
    number: int
    title: str
    state: str
    user: str | None = None
    html_url: str
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    labels: tuple[str, ...] = Field(default_factory=tuple)


class GitHubPullRequestSummary(BaseModel):
    """Normalized summary of a GitHub pull request."""

    model_config = ConfigDict(frozen=True)

    id: int
    number: int
    title: str
    state: str
    user: str | None = None
    html_url: str
    draft: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    merged_at: str | None = None


def normalize_github_user(data: dict[str, Any]) -> dict[str, Any]:
    """Parse raw GitHub user dictionary into a sanitized serializable dictionary."""
    model = GitHubUserSummary(
        id=int(data["id"]),
        login=str(data["login"]),
        type=str(data.get("type", "User")),
        html_url=str(data.get("html_url", "")),
        avatar_url=str(data["avatar_url"]) if data.get("avatar_url") else None,
        name=str(data["name"]) if data.get("name") else None,
    )
    return model.model_dump()


def normalize_github_repo(data: dict[str, Any]) -> dict[str, Any]:
    """Parse raw GitHub repository dictionary into a sanitized serializable dictionary."""
    owner_login = ""
    if isinstance(data.get("owner"), dict):
        owner_login = str(data["owner"].get("login", ""))
    elif isinstance(data.get("owner"), str):
        owner_login = data["owner"]

    model = GitHubRepoSummary(
        id=int(data["id"]),
        name=str(data["name"]),
        full_name=str(data.get("full_name", f"{owner_login}/{data['name']}")),
        owner=owner_login,
        description=str(data["description"]) if data.get("description") else None,
        private=bool(data.get("private", False)),
        html_url=str(data.get("html_url", "")),
        default_branch=str(data.get("default_branch", "main")),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )
    return model.model_dump()


def normalize_github_issue(data: dict[str, Any]) -> dict[str, Any]:
    """Parse raw GitHub issue dictionary into a sanitized serializable dictionary."""
    user_login = None
    if isinstance(data.get("user"), dict):
        user_login = str(data["user"].get("login", ""))

    labels: list[str] = []
    if isinstance(data.get("labels"), list):
        for lbl in data["labels"]:
            if isinstance(lbl, dict) and "name" in lbl:
                labels.append(str(lbl["name"]))
            elif isinstance(lbl, str):
                labels.append(lbl)

    model = GitHubIssueSummary(
        id=int(data["id"]),
        number=int(data["number"]),
        title=str(data.get("title", "")),
        state=str(data.get("state", "open")),
        user=user_login,
        html_url=str(data.get("html_url", "")),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
        closed_at=str(data["closed_at"]) if data.get("closed_at") else None,
        labels=tuple(labels),
    )
    return model.model_dump()


def normalize_github_pull_request(data: dict[str, Any]) -> dict[str, Any]:
    """Parse raw GitHub pull request dictionary into a sanitized serializable dictionary."""
    user_login = None
    if isinstance(data.get("user"), dict):
        user_login = str(data["user"].get("login", ""))

    model = GitHubPullRequestSummary(
        id=int(data["id"]),
        number=int(data["number"]),
        title=str(data.get("title", "")),
        state=str(data.get("state", "open")),
        user=user_login,
        html_url=str(data.get("html_url", "")),
        draft=bool(data.get("draft", False)),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
        merged_at=str(data["merged_at"]) if data.get("merged_at") else None,
    )
    return model.model_dump()
