from __future__ import annotations

import datetime as dt
import decimal
import enum
import importlib
import inspect
import pkgutil
from collections.abc import Awaitable
from typing import Annotated
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

import test_custom as conftest


class LocalEnum(enum.Enum):
    VALUE = "value"


class EmptyModel(BaseModel):
    pass


@patch("test_custom.pkgutil.iter_modules", autospec=True)
def test_iter_helpers_skip_private_modules(iter_modules) -> None:
    iter_modules.return_value = [pkgutil.ModuleInfo(None, "_private", False)]
    assert conftest.iter_model_classes() == []
    assert conftest.iter_enum_classes() == []
    assert conftest.iter_api_classes() == []


def test_annotation_helpers_cover_edge_types() -> None:
    assert conftest.allows_none(Annotated[str | None, "meta"])
    assert conftest.value_for_annotation(tuple[str, int]) == ("value", 1)
    assert conftest.value_for_annotation(bytes) == b"value"
    assert conftest.value_for_annotation(decimal.Decimal) == decimal.Decimal("1.5")
    assert conftest.value_for_annotation(EmptyModel) == {}
    assert conftest.value_for_annotation(object) == "value"


@patch("test_custom.get_args", autospec=True, return_value=(type(None),))
@patch("test_custom.get_origin", autospec=True, return_value=conftest.Union)
def test_unwrap_annotation_handles_empty_optional_union(get_origin, get_args) -> None:
    assert conftest._unwrap_annotation(object) is None


def test_field_and_parameter_helpers_cover_named_overrides() -> None:
    assert conftest.value_for_field("enum", LocalEnum) is LocalEnum.VALUE
    assert conftest.value_for_field("goal_type", str) == "TB"
    assert conftest.value_for_field("debt_transaction_type", str) == "payment"
    assert conftest.value_for_field("frequency", str) == "never"
    assert conftest.value_for_field("type", str) == "transaction"
    assert conftest.value_for_parameter("month", str) == "2024-01-01"
    assert conftest.value_for_parameter("since_date", dt.date) == dt.date(2024, 1, 2)
    assert conftest.value_for_parameter("type", str) == "uncategorized"
    assert conftest.value_for_parameter("last_knowledge_of_server", int) == 1
    assert conftest.value_for_parameter("amount", int) == 1


def _iter_generated_test_classes() -> list[type[Any]]:
    test_classes: list[type[Any]] = []
    for module_info in pkgutil.iter_modules(importlib.import_module("test").__path__):
        module = importlib.import_module(f"test.{module_info.name}")
        test_classes.extend(obj for _, obj in inspect.getmembers(module, inspect.isclass) if obj.__module__ == module.__name__)
    return test_classes


@pytest.mark.asyncio
async def test_generated_unittest_stubs_execute_make_instance_methods() -> None:
    for test_class in _iter_generated_test_classes():
        instance = test_class()
        instance.setUp()
        if hasattr(instance, "make_instance"):
            assert instance.make_instance(include_optional=False) is None
            assert instance.make_instance(include_optional=True) is None
        for name in dir(instance):
            if name.startswith("test"):
                result = getattr(instance, name)()
                if isinstance(result, Awaitable):
                    await result
        instance.tearDown()
