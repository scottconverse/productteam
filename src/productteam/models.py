"""Pydantic models for productteam.toml configuration."""

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """User's project metadata (not the productteam package version)."""
    name: str = ""
    version: str = "0.1.0"  # default for new user projects, not the package version


class PipelineConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_base: str = ""
    max_loops: int = 3
    max_sprints: int = 8
    require_evaluator: bool = True
    require_design_review: bool = True
    stage_timeout_seconds: int = 300
    planner_timeout_seconds: int = 600
    builder_timeout_seconds: int = 600
    builder_max_tool_calls: int = 75
    evaluator_max_tool_calls: int = 25
    doc_writer_max_tool_calls: int = 100
    skills_dir: str = ".claude/skills"
    quality: str = "standard"  # "standard" | "thorough" | "strict"
    auto_approve: bool = False


class GatesConfig(BaseModel):
    prd_approval: bool = True
    sprint_approval: bool = True
    ship_approval: bool = True


class ForgeConfig(BaseModel):
    enabled: bool = False
    queue_backend: str = "file"
    notification_backend: str = "none"
    notification_url: str = ""
    status_host: str = "127.0.0.1"
    status_port: int = 7654
    github_repo: str = ""
    poll_interval_seconds: int = 10


class ProductTeamConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    forge: ForgeConfig = Field(default_factory=ForgeConfig)
