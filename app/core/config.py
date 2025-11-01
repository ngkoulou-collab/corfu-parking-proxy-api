from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Tuple
import os

def _parse_bbox(v: str) -> Tuple[float, float, float, float]:
    parts = [p.strip() for p in v.split(",")]
    if len(parts) != 4:
        raise ValueError("CORFU_BBOX must have 4 comma-separated numbers")
    return tuple(map(float, parts))  # type: ignore

class Settings(BaseSettings):
    PARKING_PROVIDER: str = "mock"
    REFRESH_INTERVAL_SECONDS: int = 30

    TOMTOM_API_KEY: str = ""
    CORFU_BBOX: Tuple[float, float, float, float] = Field(
        default_factory=lambda: (19.9100, 39.6100, 19.9400, 39.6400)
    )
    GRID_SPACING_METERS: int = 250
    MAX_TOMTOM_CALLS: int = 300

    class Config:
        env_file = ".env"
        case_sensitive = False

    def load_bbox_from_env(self) -> None:
        raw = os.getenv("CORFU_BBOX")
        if raw:
            self.CORFU_BBOX = _parse_bbox(raw)

settings = Settings()
settings.load_bbox_from_env()
