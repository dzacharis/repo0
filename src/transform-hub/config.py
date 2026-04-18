from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Keycloak
    keycloak_url: str = Field(
        default="http://keycloak.keycloak.svc.cluster.local:8080",
        description="Base URL of the Keycloak server (no trailing slash)",
    )
    keycloak_realm: str = Field(default="maltego-hub")
    keycloak_client_id: str = Field(default="transform-hub")
    keycloak_admin_client_secret: str = Field(
        default="",
        description="Client secret for the 'transform-hub-admin' Keycloak client "
                    "(used to create/delete client registrations via the Admin API)",
    )
    required_scope: str = Field(
        default="transforms:execute",
        description="JWT scope required to execute transforms",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"

    # Hub metadata (returned in the /manifest endpoint)
    hub_name: str = "Platform Transform Hub"
    hub_url: str = "https://api.example.com/transforms"
    hub_version: str = "1.0.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
