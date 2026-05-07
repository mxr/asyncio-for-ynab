from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from asyncio_for_ynab.api_response import ApiResponse
from test_custom import iter_api_classes
from test_custom import value_for_parameter


class FakeResponse:
    status = 200
    headers = {"content-type": "application/json"}
    data = b"{}"
    response = "raw-response"

    async def read(self) -> bytes:
        return self.data


class FakeApiClient:
    def __init__(self, *, default_content_type: str | None = "application/json") -> None:
        self.calls: list[dict[str, Any]] = []
        self.configuration = SimpleNamespace(date_format="%Y-%m-%d")
        self.default_content_type = default_content_type

    def select_header_accept(self, accepts: list[str]) -> str | None:
        return "application/json" if "application/json" in accepts else accepts[0] if accepts else None

    def select_header_content_type(self, content_types: list[str]) -> str | None:
        return self.default_content_type if content_types else None

    def param_serialize(self, **kwargs: Any) -> tuple[str, str, dict[str, str], Any, list[Any]]:
        self.calls.append(kwargs)
        return kwargs["method"], "https://example.invalid" + kwargs["resource_path"], kwargs["header_params"], kwargs["body"], kwargs["post_params"]

    async def call_api(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls.append({"call_api": args, **kwargs})
        return FakeResponse()

    def response_deserialize(self, response_data: FakeResponse, response_types_map: dict[str, str | None]) -> ApiResponse[Any]:
        self.calls.append({"response_deserialize": response_types_map})
        return ApiResponse(
            status_code=response_data.status, data=SimpleNamespace(ok=True), headers=response_data.headers, raw_data=response_data.data
        )


def _method_arguments(method: Any, *, include_optional: bool = True, include_private: bool = False) -> dict[str, Any]:
    signature = inspect.signature(method)
    arguments: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if not include_private and name.startswith("_"):
            continue
        if name == "_content_type":
            arguments[name] = "application/json"
        elif name == "_headers":
            arguments[name] = {"Accept": "application/json"}
        elif name == "_request_auth":
            arguments[name] = None
        elif name == "_host_index":
            arguments[name] = 0
        elif name == "_request_timeout":
            arguments[name] = None
        elif not name.startswith("_") and (include_optional or parameter.default is inspect.Parameter.empty):
            arguments[name] = value_for_parameter(name, parameter.annotation)
    return arguments


@pytest.mark.asyncio
@pytest.mark.parametrize("api_class", iter_api_classes(), ids=lambda cls: cls.__name__)
async def test_generated_api_methods_serialize_and_call(api_class: type[Any]) -> None:
    api = api_class(FakeApiClient())
    methods = [method for name, method in inspect.getmembers(api, inspect.ismethod) if not name.startswith("_")]

    for method in methods:
        result = await method(**_method_arguments(method))
        assert result
        result = await method(**_method_arguments(method, include_optional=False))
        assert result
        result = await method(**_method_arguments(method, include_private=True))
        assert result

    if api_class.__name__ == "TransactionsApi":
        serializers = [
            method
            for name, method in inspect.getmembers(api, inspect.ismethod)
            if name.startswith("_get_transactions") and name.endswith("_serialize")
        ]
        for serializer in serializers:
            arguments = _method_arguments(serializer, include_private=True)
            if "since_date" in arguments:  # pragma: no branch
                arguments["since_date"] = "not-a-date"
            serializer(**arguments)


@pytest.mark.parametrize("api_class", iter_api_classes(), ids=lambda cls: cls.__name__)
def test_generated_api_serializers_handle_absent_default_content_type(api_class: type[Any]) -> None:
    api = api_class(FakeApiClient(default_content_type=None))
    serializers = [method for name, method in inspect.getmembers(api, inspect.ismethod) if name.endswith("_serialize")]

    for serializer in serializers:
        arguments = _method_arguments(serializer, include_optional=False, include_private=True)
        arguments["_content_type"] = None
        serializer(**arguments)


@pytest.mark.parametrize("api_class", iter_api_classes(), ids=lambda cls: cls.__name__)
def test_generated_api_serializers_handle_absent_params(api_class: type[Any]) -> None:
    api = api_class(FakeApiClient())
    serializers = [method for name, method in inspect.getmembers(api, inspect.ismethod) if name.endswith("_serialize")]

    for serializer in serializers:
        arguments = _method_arguments(serializer, include_private=True)
        for name in inspect.signature(serializer).parameters:
            if not name.startswith("_"):
                arguments[name] = None
        serializer(**arguments)
