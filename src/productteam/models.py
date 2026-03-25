"""Pydantic models for productteam.toml configuration."""

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    name: str = ""
    version: str = "0.1.0"


class PipelineConfig(BaseModel):
    max_loops: int = 3
    model: str = "claude-sonnet-4-6"
    require_evaluator: bool = True
    require_design_review: bool = True


class GatesConfig(BaseModel):
    prd_approval: bool = True
    sprint_approval: bool = True
    ship_approval: bool = True


class ProductTeamConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
