from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.application import normalize_match_text


class CompanyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=160)
    normalized_name: str | None = Field(default=None, max_length=160)
    domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("normalized_name", mode="before")
    @classmethod
    def empty_strings_are_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("domains", mode="before")
    @classmethod
    def normalize_domains(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value

        deduped: list[str] = []
        seen: set[str] = set()
        for item in value:
            domain = str(item).strip().lower()
            if domain and domain not in seen:
                seen.add(domain)
                deduped.append(domain)
        return deduped

    @model_validator(mode="after")
    def populate_normalized_name(self) -> "CompanyCreate":
        self.normalized_name = self.normalized_name or normalize_match_text(self.name)
        if self.normalized_name is None:
            raise ValueError("Company name must normalize to a non-empty value.")
        return self


class CompanyRecord(CompanyCreate):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
