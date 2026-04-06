"""
Central configuration — reads from environment variables (loaded from .env).

Usage anywhere in the codebase:
    from src.config import config
    print(config.ANTHROPIC_API_KEY)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Config:
    # ── Anthropic / Claude ────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # claude-sonnet-4-6 balances cost, speed, and accuracy for bulk classification
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    CLAUDE_MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))
    # Seconds to sleep between Claude API calls to stay within rate limits
    API_RATE_LIMIT_DELAY: float = float(os.getenv("API_RATE_LIMIT_DELAY", "0.5"))

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://localhost/racial_covenants"
    )

    # ── File storage ──────────────────────────────────────────────────────
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))

    @property
    def IMAGES_DIR(self) -> Path:
        return self.DATA_DIR / "images"

    @property
    def UPLOADS_DIR(self) -> Path:
        return self.DATA_DIR / "uploads"

    @property
    def EXPORTS_DIR(self) -> Path:
        return self.DATA_DIR / "exports"

    # ── OCR ───────────────────────────────────────────────────────────────
    # DPI for PDF → image conversion. 300 is the OCR sweet spot for these docs.
    PDF_DPI: int = int(os.getenv("PDF_DPI", "300"))
    # Pages below this Tesseract confidence score get a Claude Vision fallback
    OCR_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.5")
    )
    # Override if tesseract is not on PATH
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

    def ensure_dirs(self) -> None:
        """Create all required data directories if they don't exist."""
        for d in [self.DATA_DIR, self.IMAGES_DIR, self.UPLOADS_DIR, self.EXPORTS_DIR]:
            d.mkdir(parents=True, exist_ok=True)


config = Config()
