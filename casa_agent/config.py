"""Configuration from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

IDEALISTA_API_KEY = os.getenv("IDEALISTA_API_KEY", "")
IDEALISTA_SECRET = os.getenv("IDEALISTA_SECRET", "")

# Comma-separated list of sources: demo, idealista, fotocasa, spotahome, habitaclia, pisos.
# "demo" always works offline; spotahome and habitaclia need no key.
SOURCES = [s.strip() for s in os.getenv("CASA_SOURCES", "demo").split(",") if s.strip()]

# How many results to show in the survey
TOP_N = int(os.getenv("CASA_TOP_N", "8"))

# Polite scraping
SCRAPE_TIMEOUT = float(os.getenv("CASA_SCRAPE_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "CASA_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 casa-agent/0.1 (student project)",
)
