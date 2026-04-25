from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql://postgres:password@localhost:5432/scamshield"

    @property
    def resolved_database_url(self) -> str:
        import os
        # AWS Lambda provides LAMBDA_TASK_ROOT. If present, we are in Lambda.
        if os.environ.get("LAMBDA_TASK_ROOT"):
            # Move SQLite to /tmp for write access
            return "sqlite:////tmp/scamshield.sqlite"
        return self.database_url

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:8080",
        ]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_path: str = "./data/scorer.pkl"

    auto_seed_on_empty: bool = True
    demo_overrides_enabled: bool = True

    api_latency_target_ms: int = 400

    ai_scoring_enabled: bool = True
    bedrock_model_id: str = "anthropic.claude-haiku-4-5-20251001-v1:0"
    ai_scoring_timeout_seconds: float = 0.30
    model_blend_weight: float = 0.55

    # AWS ML settings (Layer 3)
    aws_region: str = "ap-southeast-1"
    sagemaker_mule_endpoint: str = ""  # e.g. "scamshield-mule-graphsage-v1"
    fraud_detector_id: str = ""  # e.g. "scamshield_mule_detector"
    fraud_detector_event_type: str = "account_registration_event"
    l3_graph_refresh_interval_minutes: int = 15
    l3_fallback_to_networkx: bool = True


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
