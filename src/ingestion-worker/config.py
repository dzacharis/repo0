"""Runtime configuration — all values come from environment variables (injected by Dapr)."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Dapr ──────────────────────────────────────────────────────────────────
    dapr_http_port: int = 3500
    app_port: int = 8080
    pubsub_name: str = "entity-events"
    topic_name: str = "entity-graph"

    # ── OpenSearch ────────────────────────────────────────────────────────────
    opensearch_host: str = "opensearch-cluster-master.opensearch.svc.cluster.local"
    opensearch_port: int = 9200
    opensearch_username: str = "admin"
    opensearch_password: str = Field(default="", alias="OPENSEARCH_PASSWORD")
    opensearch_use_tls: bool = False

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://neo4j.neo4j.svc.cluster.local:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")

    # ── Worker settings ───────────────────────────────────────────────────────
    # Max concurrent event processing goroutines
    max_concurrent_events: int = 10
    # Retry delay in seconds on transient write failures
    write_retry_delay: float = 2.0
    # Whether to write to OpenSearch
    enable_opensearch: bool = True
    # Whether to write to Neo4j
    enable_neo4j: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


settings = Settings()
