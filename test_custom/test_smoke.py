from __future__ import annotations

import re
from pathlib import Path

import asyncio_for_ynab


def test_version_matches_spec() -> None:
    spec = Path("config/spec.yaml").read_text()
    match = re.search(r"^  version: (?P<version>.+)$", spec, flags=re.MULTILINE)

    assert match is not None
    assert asyncio_for_ynab.__version__ == match.group("version")


def test_async_client_can_be_constructed() -> None:
    configuration = asyncio_for_ynab.Configuration(access_token="token")

    assert configuration.access_token == "token"
    assert asyncio_for_ynab.ApiClient(configuration)


def test_representative_apis_are_exported() -> None:
    assert "PlansApi" in vars(asyncio_for_ynab)
    assert "UserApi" in vars(asyncio_for_ynab)
