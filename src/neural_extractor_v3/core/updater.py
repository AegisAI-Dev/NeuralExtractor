"""GitHub release update checks for Neural Extractor V3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from neural_extractor_v3.config import (
    APP_NAME,
    GITHUB_LATEST_RELEASE_API,
    GITHUB_RELEASES_URL,
    UPDATE_CHECK_TIMEOUT_SECONDS,
    VERSION,
)


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """Information about a newer GitHub release."""

    version: str
    tag_name: str
    name: str
    html_url: str
    download_url: str
    published_at: str
    body: str


def version_tuple(value: str) -> tuple[int, ...]:
    """Convert a version or tag such as v3.1.0 to a comparable tuple."""
    match = re.search(r"(\d+(?:\.\d+){0,3})", value or "")
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer_version(candidate: str, current: str) -> bool:
    """Return True when candidate is newer than current."""
    left = version_tuple(candidate)
    right = version_tuple(current)
    max_len = max(len(left), len(right))
    left += (0,) * (max_len - len(left))
    right += (0,) * (max_len - len(right))
    return left > right


class UpdateChecker:
    """Checks GitHub Releases for a newer Windows build."""

    def __init__(
        self,
        api_url: str = GITHUB_LATEST_RELEASE_API,
        releases_url: str = GITHUB_RELEASES_URL,
        timeout: int = UPDATE_CHECK_TIMEOUT_SECONDS,
    ) -> None:
        self.api_url = api_url
        self.releases_url = releases_url
        self.timeout = timeout

    def check(self, current_version: str = VERSION) -> UpdateInfo | None:
        response = requests.get(
            self.api_url,
            timeout=self.timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{APP_NAME.replace(' ', '-')}/{current_version}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        return self.parse_release(payload, current_version)

    def parse_release(self, payload: dict[str, Any], current_version: str = VERSION) -> UpdateInfo | None:
        if payload.get("draft") or payload.get("prerelease"):
            return None

        tag_name = str(payload.get("tag_name") or "")
        if not tag_name or not is_newer_version(tag_name, current_version):
            return None

        download_url = self._select_windows_asset(payload.get("assets") or [])
        return UpdateInfo(
            version=".".join(str(part) for part in version_tuple(tag_name)),
            tag_name=tag_name,
            name=str(payload.get("name") or tag_name),
            html_url=str(payload.get("html_url") or self.releases_url),
            download_url=download_url,
            published_at=str(payload.get("published_at") or ""),
            body=str(payload.get("body") or ""),
        )

    @staticmethod
    def _select_windows_asset(assets: list[dict[str, Any]]) -> str:
        exe_assets = [
            asset
            for asset in assets
            if str(asset.get("name") or "").lower().endswith(".exe")
            and str(asset.get("browser_download_url") or "")
        ]
        if not exe_assets:
            return ""

        for asset in exe_assets:
            name = str(asset.get("name") or "").lower()
            if "neuralextractorv3" in name or "neural-extractor-v3" in name:
                return str(asset["browser_download_url"])
        return str(exe_assets[0]["browser_download_url"])
