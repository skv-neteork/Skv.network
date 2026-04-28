from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal, Dict, Any, List
import re

class ContentCode(BaseModel):
    language: str
    snippet: str
    dependencies: Optional[List[str]] = None

class ContentMedia(BaseModel):
    url: str
    description: Optional[str] = None

class Content(BaseModel):
    text: Optional[str] = None
    code: Optional[ContentCode] = None
    media: Optional[ContentMedia] = None
    structured: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def check_content_exists(self):
        if not any([self.text, self.code, self.media]):
            raise ValueError("content должен содержать text, code или media")
        return self

class Insights(BaseModel):
    summary: str = Field(..., min_length=10, max_length=300)
    domain: List[Literal["engineering", "life", "productivity", "career", "science", "design", "other"]] = Field(..., min_length=1, max_length=3)
    tags: List[str] = Field(..., min_length=2, max_length=8)
    status: Literal["concept", "verified", "deprecated"] = "concept"
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        pattern = re.compile(r"^[a-z0-9_]{3,25}$")
        for tag in v:
            if not pattern.match(tag):
                raise ValueError(f"Тег '{tag}' не соответствует формату: a-z0-9_, 3-25 символов")
        return v

class Author(BaseModel):
    mode: Literal["anonymous", "pseudonym", "attributed"]
    value: Optional[str] = None

    @model_validator(mode="after")
    def check_value_if_not_anonymous(self):
        if self.mode != "anonymous" and not self.value:
            raise ValueError("author.value обязателен, если mode != 'anonymous'")
        return self

class Collaboration(BaseModel):
    needs_review: bool = False
    review_focus: Optional[List[str]] = None
    target_domains: Optional[List[str]] = None
    deadline: Optional[str] = None

class Relations(BaseModel):
    review_of: Optional[str] = None
    version_of: Optional[str] = None
    supersedes: Optional[str] = None

class UserFields(BaseModel):
    type: Literal["text", "code", "image", "video", "audio", "mixed"]
    title: Optional[str] = Field(None, max_length=120)
    language: Optional[str] = Field(None, min_length=2, max_length=5)
    content: Content
    insights: Insights
    author: Author
    license: Literal["CC-BY-4.0", "MIT", "public-domain"]
    collaboration: Optional[Collaboration] = None
    relations: Optional[Relations] = None

class SKVEntryRequest(BaseModel):
    skv_version: Literal["1.0"]
    user_fields: UserFields