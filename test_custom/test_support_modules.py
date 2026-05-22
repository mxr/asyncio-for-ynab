from __future__ import annotations

import datetime as dt
import decimal
import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from asyncio_for_ynab import rest
from asyncio_for_ynab.api_client import ApiClient
from asyncio_for_ynab.configuration import Configuration
from asyncio_for_ynab.configuration import HostSetting
from asyncio_for_ynab.exceptions import ApiAttributeError
from asyncio_for_ynab.exceptions import ApiException
from asyncio_for_ynab.exceptions import ApiKeyError
from asyncio_for_ynab.exceptions import ApiTypeError
from asyncio_for_ynab.exceptions import ApiValueError
from asyncio_for_ynab.exceptions import BadRequestException
from asyncio_for_ynab.exceptions import ConflictException
from asyncio_for_ynab.exceptions import ForbiddenException
from asyncio_for_ynab.exceptions import NotFoundException
from asyncio_for_ynab.exceptions import render_path
from asyncio_for_ynab.exceptions import ServiceException
from asyncio_for_ynab.exceptions import UnauthorizedException
from asyncio_for_ynab.exceptions import UnprocessableEntityException
from asyncio_for_ynab.models.account_response import AccountResponse
from asyncio_for_ynab.models.account_response_data import AccountResponseData
from asyncio_for_ynab.models.account_type import AccountType
from test_custom import model_payload


class LocalEnum(Enum):
    VALUE = "value"


class ObjectWithDict:
    def __init__(self) -> None:
        self.value = 1


class ObjectWithListDict:
    def to_dict(self) -> list[dict[str, str]]:
        return [{"value": "yes"}]


@pytest.fixture
def configuration(tmp_path: Path) -> Configuration:
    config = Configuration(host="https://api.example", access_token="token")
    object.__setattr__(config, "temp_folder_path", str(tmp_path))
    return config


@pytest.fixture
def api_client(configuration: Configuration) -> ApiClient:
    return ApiClient(configuration=configuration, header_name="X-Test", header_value="yes", cookie="session=1")


def http_response(status: int = 200, content: bytes = b"{}", headers: dict[str, str] | None = None) -> rest.RESTResponse:
    response = httpx.Response(
        status, content=content, headers=headers or {"content-type": "application/json"}, request=httpx.Request("GET", "https://api.example")
    )
    return rest.RESTResponse(response)


@pytest.mark.asyncio
async def test_api_client_defaults_headers_and_context_manager(configuration: Configuration) -> None:
    client = ApiClient(configuration=configuration, header_name="X-Token", header_value="value", cookie="cookie=value")
    with patch.object(client.rest_client, "close", autospec=True) as close:
        assert client.user_agent == client.default_headers["User-Agent"]
        client.user_agent = "custom-agent"
        client.set_default_header("X-Other", "other")
        async with client as entered:
            assert entered is client
        close.assert_awaited_once()
    assert client.default_headers["X-Token"] == "value"
    assert client.default_headers["X-Other"] == "other"


def test_api_client_default_singleton(configuration: Configuration) -> None:
    previous = ApiClient._default
    try:
        ApiClient.set_default(ApiClient(configuration=configuration))
        assert ApiClient.get_default() is ApiClient._default
        ApiClient.set_default(None)
        assert isinstance(ApiClient.get_default(), ApiClient)
    finally:
        ApiClient.set_default(previous)


def test_param_serialize_formats_all_request_parts(api_client: ApiClient, tmp_path: Path) -> None:
    upload = tmp_path / "upload.txt"
    upload.write_text("hello")
    method, url, headers, body, post_params = api_client.param_serialize(
        "POST",
        "/plans/{plan_id}/items",
        path_params={"plan_id": "a/b"},
        query_params={"flag": True, "count": 2, "payload": {"a": 1}, "tags": ["a", "b"]},
        header_params={"X-Header": ["a", "b"]},
        body={"when": dt.date(2024, 1, 2), "amount": decimal.Decimal("1.5")},
        post_params={"form": ["x", "y"]},
        files={"file": [str(upload), b"bytes", ("named.bin", b"data")]},
        auth_settings=["bearer"],
        collection_formats={"X-Header": "pipes", "tags": "multi", "form": "ssv"},
        _host="https://operation.example",
    )
    assert method == "POST"
    assert url.startswith("https://operation.example/plans/a%2Fb/items?")
    assert "flag=true" in url
    assert headers["Authorization"] == "Bearer token"
    assert headers["Cookie"] == "session=1"
    assert headers["X-Header"] == "a|b"
    assert body == {"when": "2024-01-02", "amount": "1.5"}
    assert len(post_params) == 4


def test_param_serialize_handles_empty_parts(configuration: Configuration) -> None:
    client = ApiClient(configuration=configuration)
    client.default_headers = {}
    method, url, headers, body, post_params = client.param_serialize(
        "GET",
        "/items",
        collection_formats=None,
        query_params=None,
        path_params=None,
        header_params=None,
        body=None,
        post_params=None,
        files=None,
        auth_settings=None,
    )
    assert method == "GET"
    assert url == "https://api.example/items"
    assert headers == {}
    assert body is None
    assert post_params is None

    configuration.ignore_operation_servers = True
    assert client.param_serialize("GET", "/items", _host="https://ignored.example")[1] == "https://api.example/items"
    assert client.param_serialize("POST", "/items", post_params={"a": ["b", "c"]}, collection_formats={"a": "csv"})[4] == [("a", "b,c")]


@pytest.mark.parametrize(
    ("collection_format", "expected"),
    [
        pytest.param("multi", [("k", "a"), ("k", "b")], id="multi"),
        pytest.param("ssv", [("k", "a b")], id="ssv"),
        pytest.param("tsv", [("k", "a\tb")], id="tsv"),
        pytest.param("pipes", [("k", "a|b")], id="pipes"),
        pytest.param("csv", [("k", "a,b")], id="csv"),
    ],
)
def test_parameters_to_tuples_collection_formats(api_client: ApiClient, collection_format: str, expected: list[tuple[str, str]]) -> None:
    assert api_client.parameters_to_tuples({"k": ["a", "b"]}, {"k": collection_format}) == expected
    assert api_client.parameters_to_tuples({"n": "v"}, None) == [("n", "v")]


@pytest.mark.parametrize(
    ("collection_format", "expected"),
    [
        pytest.param("multi", "k=a&k=b", id="multi"),
        pytest.param("ssv", "k=a b", id="ssv"),
        pytest.param("tsv", "k=a\tb", id="tsv"),
        pytest.param("pipes", "k=a|b", id="pipes"),
        pytest.param("csv", "k=a,b", id="csv"),
    ],
)
def test_parameters_to_url_query_collection_formats(api_client: ApiClient, collection_format: str, expected: str) -> None:
    assert api_client.parameters_to_url_query({"k": ["a", "b"]}, {"k": collection_format}) == expected
    assert api_client.parameters_to_url_query({"n": 1}, None) == "n=1"


def test_files_parameters_accept_supported_shapes(api_client: ApiClient, tmp_path: Path) -> None:
    upload = tmp_path / "upload.txt"
    upload.write_text("hello")
    files_parameters = object.__getattribute__(api_client, "files_parameters")
    params = files_parameters({"path": str(upload), "bytes": b"bytes", "tuple": ("name.txt", b"tuple"), "list": [b"one", ("two.txt", b"two")]})
    assert [name for name, _ in params] == ["path", "bytes", "tuple", "list", "list"]
    with pytest.raises(ValueError, match="Unsupported file value"):
        files_parameters({"bad": object()})


def test_header_selection(api_client: ApiClient) -> None:
    assert api_client.select_header_accept([]) is None
    assert api_client.select_header_accept(["text/plain", "application/json"]) == "application/json"
    assert api_client.select_header_accept(["text/plain"]) == "text/plain"
    assert api_client.select_header_content_type([]) is None
    assert api_client.select_header_content_type(["text/plain", "application/json"]) == "application/json"
    assert api_client.select_header_content_type(["text/plain"]) == "text/plain"


def test_update_params_for_auth_variants(api_client: ApiClient) -> None:
    headers: dict[str, str] = {}
    queries: list[tuple[str, str]] = []
    api_client.update_params_for_auth(headers, queries, [], "/", "GET", None)
    assert headers == {}
    api_client.update_params_for_auth(headers, queries, ["bearer"], "/", "GET", None)
    assert headers["Authorization"] == "Bearer token"
    api_client.update_params_for_auth(headers, queries, ["missing"], "/", "GET", None)
    api_client.update_params_for_auth(
        headers, queries, ["ignored"], "/", "GET", None, request_auth={"type": "api_key", "in": "cookie", "key": "sid", "value": "abc"}
    )
    api_client.update_params_for_auth(
        headers, queries, ["ignored"], "/", "GET", None, request_auth={"type": "api_key", "in": "query", "key": "q", "value": "v"}
    )
    api_client.update_params_for_auth(
        headers, queries, ["ignored"], "/", "GET", None, request_auth={"type": "http-signature", "in": "header", "key": "Signature", "value": "skip"}
    )
    assert headers["Cookie"] == "abc"
    assert ("q", "v") in queries
    assert "Signature" not in headers
    with pytest.raises(ApiValueError):
        api_client.update_params_for_auth(
            headers, queries, ["ignored"], "/", "GET", None, request_auth={"type": "api_key", "in": "body", "key": "x", "value": "y"}
        )


def test_sanitize_for_serialization_handles_supported_values(api_client: ApiClient) -> None:
    account_response = AccountResponse.from_dict({"data": model_payload(AccountResponseData)})
    assert api_client.sanitize_for_serialization(None) is None
    assert api_client.sanitize_for_serialization(LocalEnum.VALUE) == "value"
    assert api_client.sanitize_for_serialization(SecretStr("secret")) == "secret"
    assert api_client.sanitize_for_serialization(uuid.UUID("00000000-0000-0000-0000-000000000001")) == "00000000-0000-0000-0000-000000000001"
    assert api_client.sanitize_for_serialization(["x", dt.date(2024, 1, 2)]) == ["x", "2024-01-02"]
    assert api_client.sanitize_for_serialization((dt.date(2024, 1, 2), decimal.Decimal("1.5"))) == ("2024-01-02", "1.5")
    assert api_client.sanitize_for_serialization(account_response)["data"]
    assert api_client.sanitize_for_serialization(ObjectWithDict()) == {"value": 1}
    assert api_client.sanitize_for_serialization(ObjectWithListDict()) == [{"value": "yes"}]


@pytest.mark.asyncio
async def test_call_api_delegates_and_reraises(api_client: ApiClient) -> None:
    response = http_response()
    with patch.object(api_client.rest_client, "request", autospec=True, return_value=response):
        assert await api_client.call_api("GET", "https://api.example", header_params={"Accept": "application/json"}) is response
    with (
        patch.object(api_client.rest_client, "request", autospec=True, side_effect=ApiException(status=500, reason="boom")),
        pytest.raises(ApiException),
    ):
        await api_client.call_api("GET", "https://api.example")


@pytest.mark.asyncio
async def test_response_deserialize_success_variants(api_client: ApiClient) -> None:
    pending = http_response(content=b"{}")
    with pytest.raises(AssertionError):
        api_client.response_deserialize(pending, {"200": "object"})

    raw = http_response(content=b"raw")
    await raw.read()
    assert api_client.response_deserialize(raw, {"200": "bytes"}).data == b"raw"

    fallback = http_response(content=b'{"data": {"foo": "bar"}}')
    await fallback.read()
    result = api_client.response_deserialize(fallback, {"2XX": "object"})
    assert result.status_code == 200
    assert result.data == {"data": {"foo": "bar"}}

    text = http_response(content=b"value", headers={"content-type": "text/plain; charset=utf-8"})
    await text.read()
    assert api_client.response_deserialize(text, {"200": "str"}).data == "value"

    no_type = http_response(content=b"value")
    await no_type.read()
    assert api_client.response_deserialize(no_type, {}).data is None

    missing_content_type = rest.RESTResponse(httpx.Response(200, content=b'"value"', request=httpx.Request("GET", "https://api.example")))
    await missing_content_type.read()
    assert api_client.response_deserialize(missing_content_type, {"200": "str"}).data == "value"


@pytest.mark.asyncio
async def test_response_deserialize_file_and_error(api_client: ApiClient) -> None:
    file_response = http_response(
        content=b"file", headers={"content-type": "application/octet-stream", "Content-Disposition": 'attachment; filename="../report.txt"'}
    )
    await file_response.read()
    file_path = api_client.response_deserialize(file_response, {"200": "file"}).data
    assert Path(file_path).name == "report.txt"
    assert Path(file_path).read_bytes() == b"file"

    tmp_response = http_response(content=b"tmp", headers={"content-type": "application/octet-stream"})
    await tmp_response.read()
    assert Path(api_client.response_deserialize(tmp_response, {"200": "file"}).data).read_bytes() == b"tmp"

    fallback_response = http_response(
        content=b"fallback", headers={"content-type": "application/octet-stream", "Content-Disposition": 'attachment; filename="."'}
    )
    await fallback_response.read()
    assert Path(api_client.response_deserialize(fallback_response, {"200": "file"}).data).read_bytes() == b"fallback"

    bad = http_response(400, content=b'{"error": true}')
    await bad.read()
    with pytest.raises(BadRequestException):
        api_client.response_deserialize(bad, {"400": "object"})

    below_200 = http_response(199, content=b'{"error": true}')
    await below_200.read()
    with pytest.raises(ApiException):
        api_client.response_deserialize(below_200, {"1XX": "object"})


def test_deserialize_supported_types(api_client: ApiClient) -> None:
    assert api_client.deserialize("", "str", "application/json") == ""
    assert api_client.deserialize('{"a": 1}', "object", None) == {"a": 1}
    assert api_client.deserialize("plain", "str", None) == "plain"
    assert api_client.deserialize("plain", "str", "text/plain") == "plain"
    assert api_client.deserialize("1", "int", "application/json") == 1
    assert api_client.deserialize('"2024-01-02"', "date", "application/json") == dt.date(2024, 1, 2)
    assert api_client.deserialize('"2024-01-02T03:04:05+00:00"', "datetime", "application/json").year == 2024
    assert api_client.deserialize('"1.5"', "decimal", "application/json") == decimal.Decimal("1.5")
    assert api_client.deserialize('"00000000-0000-0000-0000-000000000001"', "UUID", "application/json") == uuid.UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    assert api_client.deserialize("true", "bool", "application/json") is True
    assert api_client.deserialize("1.5", "float", "application/json") == 1.5
    assert api_client.deserialize('["1", "2"]', "List[int]", "application/json") == [1, 2]
    assert api_client.deserialize('{"a": "1"}', "Dict[str, int]", "application/json") == {"a": 1}
    assert api_client.deserialize(
        json.dumps(api_client.sanitize_for_serialization(model_payload(AccountResponse))), "AccountResponse", "application/json"
    )
    with pytest.raises(ApiException, match="Unsupported content type"):
        api_client.deserialize("plain", "str", "application/xml")
    with pytest.raises(AssertionError):
        api_client.deserialize("[]", "List[", "application/json")
    with pytest.raises(AssertionError):
        api_client.deserialize("{}", "Dict[str]", "application/json")
    with pytest.raises(rest.ApiException):
        api_client.deserialize('"bad"', "date", "application/json")
    with pytest.raises(rest.ApiException):
        api_client.deserialize('"bad"', "datetime", "application/json")
    with pytest.raises(rest.ApiException):
        api_client.deserialize('"bad"', "AccountType", "application/json")


def test_deserialize_private_edge_cases(api_client: ApiClient) -> None:
    deserialize = object.__getattribute__(api_client, "_ApiClient__deserialize")
    deserialize_primitive = object.__getattribute__(api_client, "_ApiClient__deserialize_primitive")
    assert deserialize(None, "str") is None
    assert deserialize("1", int) == 1
    assert deserialize({"a": 1}, object) == {"a": 1}
    assert deserialize("2024-01-02", dt.date) == dt.date(2024, 1, 2)
    assert deserialize("2024-01-02T03:04:05+00:00", dt.datetime).year == 2024
    assert deserialize("1.5", decimal.Decimal) == decimal.Decimal("1.5")
    assert deserialize("00000000-0000-0000-0000-000000000001", uuid.UUID) == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert deserialize("checking", AccountType) == AccountType.CHECKING
    assert deserialize_primitive(object(), int)
    unicode_failure = Mock(side_effect=UnicodeEncodeError("utf-8", "x", 0, 1, "bad"))
    assert deserialize_primitive("x", unicode_failure) == "x"


@patch("asyncio_for_ynab.api_client.parse", autospec=True, side_effect=ImportError)
def test_deserialize_date_and_datetime_import_error(parse: Mock, api_client: ApiClient) -> None:
    assert object.__getattribute__(api_client, "_ApiClient__deserialize_date")("bad") == "bad"
    assert object.__getattribute__(api_client, "_ApiClient__deserialize_datetime")("bad") == "bad"


def test_configuration_defaults_and_auth(tmp_path: Path) -> None:
    previous = Configuration._default
    try:
        config = Configuration(
            api_key={"bearer": "key", "alias": "alias-key"},
            api_key_prefix={"bearer": "Bearer"},
            username="user",
            password="pass",
            access_token="access",
        )
        refreshed_configs: list[Configuration] = []

        def refresh_api_key_hook(refreshed_config: Configuration) -> None:
            refreshed_configs.append(refreshed_config)

        object.__setattr__(config, "refresh_api_key_hook", refresh_api_key_hook)
        assert config.get_api_key_with_prefix("bearer") == "Bearer key"
        assert config.get_api_key_with_prefix("missing", "alias") == "alias-key"
        assert config.get_api_key_with_prefix("none") is None
        assert refreshed_configs == [config, config, config]
        assert config.get_basic_auth_token() == "Basic dXNlcjpwYXNz"
        assert config.auth_settings()["bearer"]["value"] == "Bearer access"
        assert "Python SDK Debug Report" in config.to_debug_report()
        assert config.logger_format == "%(asctime)s %(levelname)s %(message)s"
        config.host = "https://custom.example"
        assert config.host == "https://custom.example"
        Configuration.set_default(config)
        assert Configuration.get_default_copy() is config
        Configuration.set_default(None)
        assert isinstance(Configuration.get_default(), Configuration)
        config.logger_format = "%(message)s"
        log_file = tmp_path / "client.log"
        config.logger_file = str(log_file)
        config.debug = True
        config.debug = False
        copied = config.__deepcopy__({})
        assert copied.host == config.host

        no_auth = Configuration(debug=True)
        no_auth.api_key["plain"] = "key"
        assert no_auth.get_basic_auth_token() == "Basic Og=="
        assert no_auth.get_api_key_with_prefix("plain") == "key"
        assert no_auth.auth_settings() == {}
        assert no_auth.get_host_settings()
    finally:
        Configuration.set_default(previous)


def test_configuration_host_settings_validation() -> None:
    config = Configuration()
    servers: list[HostSetting] = [
        {
            "url": "https://{env}.example/{version}",
            "description": "test",
            "variables": {
                "env": {"default_value": "dev", "enum_values": ["dev", "prod"], "description": ""},
                "version": {"default_value": "v1", "enum_values": [], "description": ""},
            },
        }
    ]
    assert config.get_host_from_settings(None) == config._base_path
    assert config.get_host_from_settings(0, servers=servers) == "https://dev.example/v1"
    assert config.get_host_from_settings(0, variables={"env": "prod", "version": "v2"}, servers=servers) == "https://prod.example/v2"
    with pytest.raises(ValueError, match="Invalid index"):
        config.get_host_from_settings(2, servers=servers)
    with pytest.raises(ValueError, match="invalid value"):
        config.get_host_from_settings(0, variables={"env": "stage"}, servers=servers)


@pytest.mark.parametrize(
    ("exception_class", "args"),
    [
        pytest.param(ApiTypeError, {"valid_classes": (str,), "key_type": True}, id="type"),
        pytest.param(ApiValueError, {}, id="value"),
        pytest.param(ApiAttributeError, {}, id="attribute"),
        pytest.param(ApiKeyError, {}, id="key"),
    ],
)
def test_path_aware_exceptions(exception_class: type[Exception], args: dict[str, Any]) -> None:
    exception = exception_class("bad", **{"path_to_item": ["data", 0, "name"], **args})
    assert "['data'][0]['name']" in str(exception)
    assert "bad" in str(exception_class("bad", **args))
    assert render_path(["data", 0]) == "['data'][0]"


@pytest.mark.parametrize(
    ("status", "exception_class"),
    [
        pytest.param(400, BadRequestException, id="bad-request"),
        pytest.param(401, UnauthorizedException, id="unauthorized"),
        pytest.param(403, ForbiddenException, id="forbidden"),
        pytest.param(404, NotFoundException, id="not-found"),
        pytest.param(409, ConflictException, id="conflict"),
        pytest.param(422, UnprocessableEntityException, id="unprocessable"),
        pytest.param(500, ServiceException, id="service"),
        pytest.param(418, ApiException, id="default"),
    ],
)
def test_api_exception_from_response(status: int, exception_class: type[ApiException]) -> None:
    response = http_response(status, content=b"body", headers={"x": "y"})
    with pytest.raises(exception_class) as excinfo:
        ApiException.from_response(http_resp=response, body="body", data={"parsed": True})
    assert "Reason:" in str(excinfo.value)
    assert "HTTP response headers" in str(excinfo.value)
    assert "HTTP response body" in str(excinfo.value)
    assert "HTTP response data" in str(excinfo.value)


def test_api_exception_with_http_response_decode_failure() -> None:
    response = http_response(418, content=b"\xff", headers={"x": "y"})
    exception = ApiException(http_resp=response)
    assert exception.status == 418
    assert exception.body is None
    explicit = ApiException(status=499, reason="explicit", http_resp=response, body="body")
    assert explicit.status == 499
    assert explicit.reason == "explicit"
    assert explicit.body == "body"


@pytest.mark.asyncio
async def test_rest_response_reads_once() -> None:
    response = http_response(content=b"cached", headers={"x-test": "yes"})
    assert await response.read() == b"cached"
    assert await response.read() == b"cached"
    assert response.headers["x-test"] == "yes"
    assert response.getheaders()["x-test"] == "yes"
    assert response.getheader("missing", "default") == "default"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "OPTIONS", "DELETE"])
async def test_rest_client_request_builds_supported_methods(configuration: Configuration, method: str) -> None:
    client = rest.RESTClientObject(configuration)
    pool = httpx.AsyncClient()
    client.pool_manager = pool
    headers = {"Content-Type": "application/json"}
    with patch.object(
        pool, "request", autospec=True, return_value=httpx.Response(200, content=b"{}", request=httpx.Request(method, "https://api.example"))
    ) as request:
        response = await client.request(method, "https://api.example", headers=headers, body={"ok": True}, _request_timeout=1)
        assert response.status == 200
        request.assert_awaited_once()
    await pool.aclose()


@pytest.mark.asyncio
async def test_rest_client_request_uses_defaults_and_creates_pool(configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    pool = httpx.AsyncClient()
    with (
        patch.object(rest.RESTClientObject, "_create_pool_manager", autospec=True, return_value=pool) as create_pool_manager,
        patch.object(
            pool, "request", autospec=True, return_value=httpx.Response(200, content=b"{}", request=httpx.Request("GET", "https://api.example"))
        ) as request,
    ):
        response = await client.request("GET", "https://api.example")
        assert response.status == 200
        create_pool_manager.assert_called_once_with(client)
        request.assert_awaited_once()
    await pool.aclose()


@pytest.mark.asyncio
async def test_rest_client_request_sends_json_post_params(configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    pool = httpx.AsyncClient()
    client.pool_manager = pool
    with patch.object(
        pool, "request", autospec=True, return_value=httpx.Response(200, content=b"{}", request=httpx.Request("POST", "https://api.example"))
    ) as request:
        response = await client.request("POST", "https://api.example", headers={"Content-Type": "application/json"}, post_params=[("a", "b")])
        assert response.status == 200
        request.assert_awaited_once_with(
            method="POST", url="https://api.example", timeout=300, headers={"Content-Type": "application/json"}, json={"a": "b"}
        )
    await pool.aclose()


@pytest.mark.asyncio
async def test_rest_client_request_handles_form_multipart_and_raw_body(configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    pool = httpx.AsyncClient()
    client.pool_manager = pool
    with patch.object(
        pool, "request", autospec=True, return_value=httpx.Response(200, content=b"{}", request=httpx.Request("POST", "https://api.example"))
    ) as request:
        await client.request("POST", "https://api.example", headers={"Content-Type": "application/x-www-form-urlencoded"}, post_params=[("a", "b")])
        await client.request(
            "POST",
            "https://api.example",
            headers={"Content-Type": "multipart/form-data"},
            post_params=[("file", ("name.txt", b"data", "text/plain")), ("meta", {"a": 1}), ("count", 2), ("plain", "text")],
        )
        await client.request("POST", "https://api.example", headers={"Content-Type": "multipart/form-data"}, post_params=[("plain", "text")])
        await client.request(
            "POST",
            "https://api.example",
            headers={"Content-Type": "multipart/form-data"},
            post_params=[("file", ("name.txt", b"data", "text/plain"))],
        )
        await client.request("POST", "https://api.example", headers={"Content-Type": "text/plain"}, body="raw")
        await client.request("POST", "https://api.example", headers={"Content-Type": "application/json"})
        assert request.await_count == 6
    await pool.aclose()


@pytest.mark.asyncio
async def test_rest_client_request_rejects_invalid_inputs(configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    with pytest.raises(AssertionError):
        await client.request("TRACE", "https://api.example")
    with pytest.raises(ApiValueError):
        await client.request("POST", "https://api.example", body={"a": 1}, post_params=[("a", "b")])
    with pytest.raises(ApiException):
        await client.request("POST", "https://api.example", headers={"Content-Type": "text/plain"}, body={"a": 1})


@pytest.mark.asyncio
async def test_rest_client_closes_pool(configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    pool = httpx.AsyncClient()
    client.pool_manager = pool
    with patch.object(pool, "aclose", autospec=True) as aclose:
        await client.close()
        aclose.assert_awaited_once()


@patch("asyncio_for_ynab.rest.httpx.AsyncClient", autospec=True)
@patch("asyncio_for_ynab.rest.httpx.Proxy", autospec=True)
def test_rest_client_create_pool_manager_uses_proxy(proxy: Mock, async_client: Mock, configuration: Configuration) -> None:
    configuration.proxy = "https://proxy.example"
    configuration.proxy_headers = {"X-Proxy": "yes"}
    client = rest.RESTClientObject(configuration)
    result = client._create_pool_manager()
    assert result is async_client.return_value
    proxy.assert_called_once_with(url="https://proxy.example", headers={"X-Proxy": "yes"})
    async_client.assert_called_once()


@patch("asyncio_for_ynab.rest.httpx.AsyncClient", autospec=True)
def test_rest_client_create_pool_manager_without_proxy(async_client: Mock, configuration: Configuration) -> None:
    client = rest.RESTClientObject(configuration)
    assert client._create_pool_manager() is async_client.return_value
    async_client.assert_called_once()


@patch("asyncio_for_ynab.rest.ssl.create_default_context", autospec=True)
def test_rest_client_ssl_configuration(create_default_context: Mock) -> None:
    context = Mock()
    create_default_context.return_value = context
    config = Configuration(verify_ssl=False, ssl_ca_cert="ca.pem", ca_cert_data="cert-data", cert_file="cert.pem", key_file="key.pem")
    client = rest.RESTClientObject(config)
    assert client.ssl_context is context
    context.load_cert_chain.assert_called_once_with("cert.pem", keyfile="key.pem")
    assert context.check_hostname is False
    assert context.verify_mode == rest.ssl.CERT_NONE
