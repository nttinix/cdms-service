import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BusinessProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=100)
    partner_sku: str = Field(alias="partnerSKU", min_length=1, max_length=100)
    product_name: str = Field(alias="productName", min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=32767)
    color: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=100)
    is_active: bool = Field(default=True, alias="isActive")
    units: list[str] = Field(default_factory=list)
    categories: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("units")
    @classmethod
    def normalize_units(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        encoded = {json.dumps(item, sort_keys=True, allow_nan=False) for item in value}
        return [json.loads(item) for item in sorted(encoded)]

    @model_validator(mode="after")
    def guard_excel_cell_sizes(self):
        for value in (self.units, self.categories):
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 32767:
                raise ValueError("Serialized product arrays exceed Excel cell capacity")
        return self


class Product(BusinessProduct):
    product_id: int = Field(alias="productId", ge=1, le=9_223_372_036_854_775_807)
    source_version: int = Field(alias="sourceVersion", ge=1, le=9_223_372_036_854_775_807)

    def business_data(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude={"source_version"})

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.business_data(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ProductWrite(BusinessProduct):
    unit_code: str = Field(alias="unitCode", min_length=1)
    unit_name: str = Field(alias="unitName", min_length=1)
    product_units: list[dict[str, Any]] = Field(alias="productUnits")

    def business_data(self) -> dict[str, Any]:
        result = self.model_dump(by_alias=True, exclude={"unit_code", "unit_name", "product_units"})
        if not result["units"]:
            result["units"] = [self.unit_code]
        return result
