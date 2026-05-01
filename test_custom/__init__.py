from __future__ import annotations

import datetime as dt
import decimal
import enum
import importlib
import inspect
import pkgutil
import types
import uuid
from typing import Annotated
from typing import Any
from typing import get_args
from typing import get_origin
from typing import Union

from pydantic import BaseModel

import asyncio_for_ynab.api
import asyncio_for_ynab.models


TEST_UUID = "00000000-0000-0000-0000-000000000001"


def iter_model_classes() -> list[type[BaseModel]]:
    classes: list[type[BaseModel]] = []
    for module_info in pkgutil.iter_modules(asyncio_for_ynab.models.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{asyncio_for_ynab.models.__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                classes.append(obj)
    return sorted(classes, key=lambda cls: cls.__name__)


def iter_enum_classes() -> list[type[enum.Enum]]:
    classes: list[type[enum.Enum]] = []
    for module_info in pkgutil.iter_modules(asyncio_for_ynab.models.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{asyncio_for_ynab.models.__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, enum.Enum) and obj.__module__ == module.__name__:
                classes.append(obj)
    return sorted(classes, key=lambda cls: cls.__name__)


def iter_api_classes() -> list[type[Any]]:
    classes: list[type[Any]] = []
    for module_info in pkgutil.iter_modules(asyncio_for_ynab.api.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{asyncio_for_ynab.api.__name__}.{module_info.name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if name.endswith("Api") and obj.__module__ == module.__name__:
                classes.append(obj)
    return sorted(classes, key=lambda cls: cls.__name__)


def _unwrap_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap_annotation(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        for arg in get_args(annotation):
            if arg is not type(None):
                return _unwrap_annotation(arg)
        return None
    return annotation


def allows_none(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Annotated:
        return allows_none(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        return type(None) in get_args(annotation)
    return False


def value_for_annotation(annotation: Any) -> Any:
    annotation = _unwrap_annotation(annotation)
    origin = get_origin(annotation)

    if origin is list:
        return [value_for_annotation(get_args(annotation)[0])]
    if origin is dict:
        return {"key": value_for_annotation(get_args(annotation)[1])}
    if origin is tuple:
        return tuple(value_for_annotation(arg) for arg in get_args(annotation) if arg is not Ellipsis)

    if annotation in (str, Any):
        return "value"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.5
    if annotation is bool:
        return True
    if annotation is bytes:
        return b"value"
    if annotation is dt.date:
        return dt.date(2024, 1, 2)
    if annotation is dt.datetime:
        return dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    if annotation is decimal.Decimal:
        return decimal.Decimal("1.5")
    if annotation is uuid.UUID:
        return TEST_UUID
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
        return next(iter(annotation))
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return model_payload(annotation)

    return "value"


def value_for_field(name: str, annotation: Any) -> Any:
    unwrapped = _unwrap_annotation(annotation)
    if inspect.isclass(unwrapped) and issubclass(unwrapped, enum.Enum):
        return value_for_annotation(annotation)
    if name == "goal_type":
        return "TB"
    if name == "debt_transaction_type":
        return "payment"
    if name == "frequency":
        return "never"
    if name == "type":
        return "transaction"
    return value_for_annotation(annotation)


def model_payload(model_class: type[BaseModel]) -> dict[str, Any]:
    return {field.alias or name: value_for_field(name, field.annotation) for name, field in model_class.model_fields.items()}


def value_for_parameter(name: str, annotation: Any) -> Any:
    if name.endswith("_id") or name in {"id", "plan_id", "budget_id", "account_id", "category_id", "payee_id", "transaction_id"}:
        return TEST_UUID
    if name == "month":
        return "2024-01-01"
    if name == "since_date":
        return dt.date(2024, 1, 2)
    if name == "type":
        return "uncategorized"
    if name == "last_knowledge_of_server":
        return 1
    return value_for_annotation(annotation)
