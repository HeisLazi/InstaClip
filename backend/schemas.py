"""Shared Pydantic types for the FastAPI routes."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---- Pipeline ---------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    source: str = Field(..., description="Local path or http(s) URL")
    force: bool = False


class PipelineBatchRequest(BaseModel):
    """
    Either `paths` (explicit list) or `size` (auto-pick first N
    unprocessed). When both are given, `paths` wins.
    """
    size:  int = 5
    paths: Optional[list[str]] = None


# ---- Clips ------------------------------------------------------------------

class ClipInfo(BaseModel):
    stem: str
    name: str
    bucket: str          # "output" | "positives" | "negatives"
    size_mb: float
    duration_seconds: Optional[float] = None
    mtime: float
    score: Optional[float] = None
    quality_score: Optional[float] = None
    speaker: Optional[str] = None
    has_thumbnail: bool = False
    group: str = "unsorted"
    source_vod: Optional[str] = None
    triggers: list[str] = Field(default_factory=list)
    hazard_flags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ClipMoveRequest(BaseModel):
    stem: str
    from_bucket: str     # "output" | "positives" | "negatives"
    to_bucket: str


class ClipTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class ClipReviewRequest(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    verdict: str = "undecided"  # keeper | maybe | miss | undecided
    reasons: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    caption_notes: str = ""


class PublishCreateRequest(BaseModel):
    stem: str
    bucket: str = "output"
    platform: str
    account_id: Optional[str] = None   # which configured account to post from ("all" = every account)
    account_ids: Optional[list[str]] = None  # post-to-all/selected: fan out to these accounts
    title: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scheduled_at: Optional[str] = None
    notes: str = ""
    privacy_level: Optional[str] = None
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    video_cover_timestamp_ms: Optional[int] = Field(default=None, ge=0)
    content_consent: bool = False
    tiktok_mode: str = "direct"


class TikTokAppConfigRequest(BaseModel):
    client_key: str
    client_secret: str


class TikTokOAuthStartRequest(BaseModel):
    label: str = "TikTok account"
    is_default: bool = False


class PublishAccountRequest(BaseModel):
    id: Optional[str] = None
    platform: str            # instagram | tiktok | youtube
    label: str = ""          # e.g. "@heisntlazi", "@cpt.shanyok"
    is_default: Optional[bool] = None
    user_id: Optional[str] = None
    access_token: Optional[str] = None
    graph_api_version: Optional[str] = None
    video_url_base: Optional[str] = None
    open_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None


class CaptionTemplateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    platform: str = ""


class PublishUpdateRequest(BaseModel):
    status: Optional[str] = None
    scheduled_at: Optional[str] = None
    post_url: Optional[str] = None
    notes: Optional[str] = None


class PublishCredentialsRequest(BaseModel):
    tiktok_access_token: Optional[str] = None
    tiktok_open_id: Optional[str] = None
    youtube_client_id: Optional[str] = None
    youtube_client_secret: Optional[str] = None
    youtube_refresh_token: Optional[str] = None
    instagram_user_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    instagram_video_url_base: Optional[str] = None
    instagram_graph_api_version: Optional[str] = None


# ---- Profile editor ---------------------------------------------------------

class ProfileAddRequest(BaseModel):
    key: str
    value: Any   # str or dict


class ProfileRemoveRequest(BaseModel):
    key: str
    value: Any


class ProfilePatchApply(BaseModel):
    add: dict[str, list[Any]] = Field(default_factory=dict)
    remove: dict[str, list[Any]] = Field(default_factory=dict)
    # Free-form review-tuner outputs — appended to data/clip_memory.md so the
    # chat LLM and future tuner runs honor them across sessions.
    context_rules: list[str] = Field(default_factory=list)
    slang_glossary: dict[str, str] = Field(default_factory=dict)
    avoid_patterns: list[str] = Field(default_factory=list)
    save: bool = True


# ---- Voice ------------------------------------------------------------------

class VoiceEnrollRequest(BaseModel):
    name: str = "lazi"
    seconds: int = 30
    device: Optional[int] = None


# ---- Twitch -----------------------------------------------------------------

class TwitchCredentialsRequest(BaseModel):
    client_id: str
    client_secret: str


class TwitchSyncRequest(BaseModel):
    login: str
    limit: int = 50


# ---- Train ------------------------------------------------------------------

class ClassifierTrainRequest(BaseModel):
    force: bool = False
    use_vision: Optional[bool] = None   # None = read from settings
    vision_model: Optional[str] = None
