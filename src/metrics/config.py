"""Configuration: secrets from .env / environment, app config from config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_FILE = Path("config.yaml")


class Settings(BaseSettings):
    """Secrets, read from environment / .env — never from config.yaml."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    azdo_pat: str = Field(default="", alias="AZDO_PAT")
    vm_url_override: str = Field(default="", alias="METRICS_VM_URL")


class AzureDevOpsConfig(BaseModel):
    organization: str
    project: str
    team: str
    api_version: str = "7.1"
    analytics_version: str = "v4.0-preview"

    @property
    def base_url(self) -> str:
        return f"https://dev.azure.com/{self.organization}"

    @property
    def analytics_url(self) -> str:
        return (
            f"https://analytics.dev.azure.com/{self.organization}"
            f"/{self.project}/_odata/{self.analytics_version}"
        )


class SprintsConfig(BaseModel):
    selected: list[str] = Field(default_factory=list)


class StatesConfig(BaseModel):
    done: list[str] = Field(default_factory=lambda: ["Done", "Closed"])
    in_progress: list[str] = Field(default_factory=lambda: ["Committed", "In Progress", "Active"])
    removed: list[str] = Field(default_factory=lambda: ["Removed"])


class MetricsConfig(BaseModel):
    excluded_types: list[str] = Field(default_factory=list)
    estimation_field: str = "Microsoft.VSTS.Scheduling.Effort"
    states: StatesConfig = Field(default_factory=StatesConfig)
    velocity_rolling_window: int = 3


class SyncConfig(BaseModel):
    closed_sprint_grace_days: int = 3


class ExportConfig(BaseModel):
    # Matches metrics.sh, which runs the CLI container with --network host.
    victoriametrics_url: str = "http://localhost:8428"


class PathsConfig(BaseModel):
    data_dir: str = "data"


class AppConfig(BaseModel):
    azure_devops: AzureDevOpsConfig
    sprints: SprintsConfig = Field(default_factory=SprintsConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @property
    def data_dir(self) -> Path:
        return Path(self.paths.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "metrics.duckdb"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_FILE) -> AppConfig:
        if not path.exists():
            raise FileNotFoundError(
                f"Config file '{path}' not found. Run `metrics init` first "
                f"or copy config.example.yaml to {path}."
            )
        with path.open("r", encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh) or {})

    def dump(self, path: Path = DEFAULT_CONFIG_FILE) -> None:
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                self.model_dump(mode="json"), fh, sort_keys=False, allow_unicode=True
            )
