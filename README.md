# asyncio-for-ynab

Asyncio client for the YNAB API.

This package is generated from the YNAB OpenAPI spec and uses the OpenAPI Generator Python `httpx` client.

This project is not affiliated with, endorsed by, or officially connected with YNAB.

## Install

```sh
python -m pip install asyncio-for-ynab
```

For local development:

```sh
python -m pip install -e ".[dev]"
```

## Quick Start

```python
import asyncio

from asyncio_for_ynab import ApiClient
from asyncio_for_ynab import Configuration
from asyncio_for_ynab import PlansApi
from asyncio_for_ynab import UserApi


async def main() -> None:
    configuration = Configuration(access_token="your-access-token")

    async with ApiClient(configuration) as api_client:
        user_api = UserApi(api_client)
        plans_api = PlansApi(api_client)

        user = await user_api.get_user()
        plans = await plans_api.get_plans()

    print(user)
    print(plans)


asyncio.run(main())
```

## Common Patterns

Create a client once and pass it to any generated API class:

```python
from asyncio_for_ynab import AccountsApi
from asyncio_for_ynab import ApiClient
from asyncio_for_ynab import Configuration


configuration = Configuration(access_token="your-access-token")

async with ApiClient(configuration) as api_client:
    accounts_api = AccountsApi(api_client)
    accounts = await accounts_api.get_accounts()
```

The package also exports generated models, response objects, and exceptions at the top level:

```python
from asyncio_for_ynab import AccountResponse
from asyncio_for_ynab import ApiException
from asyncio_for_ynab import TransactionResponse
```

## Development

Run the repository checks with pre-commit:

```sh
pre-commit run --all-files
```

Run the test suite:

```sh
tox -e py
```

## Versioning

Package versions mirror the YNAB API spec version. For example, spec `1.83.0` is published as `asyncio-for-ynab==1.83.0`.

Sometimes YNAB updates the spec without raising the version (for example, documentation updates). Releases are not created in this case. Install from `main` to pull in these changes.

## Changelog / Release Notes

This project publishes auto-generated release notes. For YNAB API release notes, see https://api.ynab.com/#changelog
