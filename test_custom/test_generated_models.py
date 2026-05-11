from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from pydantic import ValidationError

from test_custom import allows_none
from test_custom import iter_enum_classes
from test_custom import iter_model_classes
from test_custom import model_payload
from test_custom import value_for_annotation

if TYPE_CHECKING:
    from typing import Any
    from typing import Protocol

    from typing_extensions import Self

    class EnumWithFromJson(Protocol):
        @classmethod
        def from_json(cls, data: str) -> object: ...

    class GeneratedModel(BaseModel):
        def to_dict(self) -> dict[str, Any]: ...

        def to_json(self) -> str: ...

        def to_str(self) -> str: ...

        @classmethod
        def from_dict(cls, obj: object | None) -> Self | None: ...

        @classmethod
        def from_json(cls, json_str: str) -> Self | None: ...


@pytest.mark.parametrize("model_class", iter_model_classes(), ids=lambda cls: cls.__name__)
def test_generated_model_serialization_helpers(model_class: type[GeneratedModel], subtests: pytest.Subtests) -> None:
    payload = model_payload(model_class)

    model = model_class.from_dict(payload)
    assert model is not None
    assert model.to_dict()
    assert model.to_json()
    assert model.to_str()
    assert model_class.from_json(model.to_json()) == model
    assert model_class.from_dict(model) == model
    assert model_class.from_dict(None) is None

    nullable_payload = payload.copy()
    for name, field in model_class.model_fields.items():
        if field.default is None or allows_none(field.annotation):
            nullable_payload[field.alias or name] = None
    nullable_model = model_class.from_dict(nullable_payload)
    assert nullable_model is not None
    assert nullable_model.to_dict() is not None

    empty_model = model_class.model_construct(**dict.fromkeys(model_class.model_fields))
    assert empty_model.to_dict() is not None

    for name, field in model_class.model_fields.items():
        field_value = value_for_annotation(field.annotation)
        if isinstance(field_value, list):
            with subtests.test("list field", model=model_class.__name__, field=name):
                list_model = model_class.model_construct(**dict.fromkeys(model_class.model_fields))
                list_model.__dict__[name] = [None]
                assert list_model.to_dict() is not None


@pytest.mark.parametrize("model_class", iter_model_classes(), ids=lambda cls: cls.__name__)
def test_generated_model_validators_reject_invalid_enums(model_class: type[GeneratedModel], subtests: pytest.Subtests) -> None:
    payload = model_payload(model_class)
    invalid_field_names = {"debt_transaction_type", "frequency", "goal_type", "type"}
    for name, field in model_class.model_fields.items():
        if name in invalid_field_names and not hasattr(field.annotation, "__members__"):
            with subtests.test(model=model_class.__name__, field=name):
                invalid_payload = payload.copy()
                invalid_payload[field.alias or name] = "invalid"
                with pytest.raises(ValidationError):
                    model_class.from_dict(invalid_payload)


@pytest.mark.parametrize("enum_class", iter_enum_classes(), ids=lambda cls: cls.__name__)
def test_generated_model_enum_json_helpers(enum_class: type[EnumWithFromJson]) -> None:
    value = value_for_annotation(enum_class)
    assert enum_class.from_json(json.dumps(value.value)) == value
