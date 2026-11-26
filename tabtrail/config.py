"""Settings come from environment variables, so a person or an AI agent can run any step the same way."""
import os, pathlib
from dataclasses import dataclass, field

HOME = pathlib.Path.home()
MAC = HOME / "Library/Application Support"
LINUX = HOME / ".config"
PROFILES = {  # Chromium-family browsers share one History format
    "brave":  [MAC / "BraveSoftware/Brave-Browser/Default", LINUX / "BraveSoftware/Brave-Browser/Default"],
    "chrome": [MAC / "Google/Chrome/Default", LINUX / "google-chrome/Default"],
    "edge":   [MAC / "Microsoft Edge/Default", LINUX / "microsoft-edge/Default"],
    "arc":    [MAC / "Arc/User Data/Default"],
}

def _env(name, default): return os.environ.get("TABTRAIL_" + name, default)

REPO = pathlib.Path(__file__).resolve().parents[1]
# Run from a checkout (also an editable install): keep everything in the repo's data/ folder.
# Installed as a normal package: fall back to ~/.local/share/tabtrail.
DEFAULT_HOME = REPO / "data" if (REPO / "pyproject.toml").exists() else HOME / ".local/share/tabtrail"

@dataclass(frozen=True)
class Config:
    home: pathlib.Path
    browser: str
    profile: pathlib.Path
    claude_dir: pathlib.Path
    pi_dir: pathlib.Path
    sources: tuple
    ollama: str
    embed_model: str
    lines: str            # how long chat messages become one line: "mlx" or "truncate"
    lines_per_run: int    # cap on new LLM lines per run, so a daily run stays short
    llm_model: str
    min_seconds: int
    recent_days: int

    @property
    def db(self): return self.home / "tabtrail.duckdb"
    @property
    def raw(self): return self.home / "raw"
    @property
    def profile_md(self): return self.home / "profile.md"

def load() -> Config:
    browser = _env("BROWSER", "brave")
    prof = _env("PROFILE", "")
    profile = pathlib.Path(prof).expanduser() if prof else next((p for p in PROFILES.get(browser, []) if p.exists()), PROFILES.get(browser, [MAC])[0])
    home = pathlib.Path(_env("HOME", str(DEFAULT_HOME))).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    # local LLM weights live with the data, not in the shared Hugging Face cache
    os.environ.setdefault("HF_HUB_CACHE", str(home / "models"))
    return Config(home=home, browser=browser, profile=profile,
        claude_dir=pathlib.Path(_env("CLAUDE_DIR", str(HOME / ".claude/projects"))).expanduser(),
        pi_dir=pathlib.Path(_env("PI_DIR", str(HOME / ".pi/agent/sessions"))).expanduser(),
        sources=tuple(s.strip() for s in _env("SOURCES", "brave,claude,pi").split(",") if s.strip()),
        ollama=_env("OLLAMA", "http://localhost:11434"), embed_model=_env("EMBED_MODEL", "nomic-embed-text"),
        lines=_env("LINES", "mlx"), lines_per_run=int(_env("LINES_PER_RUN", "200")),
        llm_model=_env("LLM_MODEL", "mlx-community/Qwen3-1.7B-4bit"),
        min_seconds=int(_env("MIN_SECONDS", "10")),
        recent_days=int(_env("RECENT_DAYS", "14")))
