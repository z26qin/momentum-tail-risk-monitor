"""Setup for final_mvp_demo.ipynb — one full MVP run; steps below render layers."""

from pathlib import Path
import math
import re
import sys

import pandas as pd
from IPython.display import Markdown, display

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mvp.config import MVPConfig
from src.mvp.pipeline import run_mvp
from src.mvp.crowding_context import build_positioning_snapshot
from src.mvp.evidence_interpretation import public_positioning_proxy_items
from src.mvp.deepseek_evidence_interpreter import DeepSeekEvidenceInterpreter
from src.mvp.deepseek_pm_response_interpreter import DeepSeekPMResponseInterpreter
from src.mvp.pm_response import CATEGORY_LABELS
from src.evidence.deepseek_explainer import _load_dotenv_if_present
from src.risk.dm_engine import build_primary_assessment
from src.regime.market_state import build_regime_history

# Demo default for the PPT: LIVE DeepSeek (requires DEEPSEEK_API_KEY in .env).
# Set to False for a fully offline deterministic run (no API call).
USE_LLM = True

CONFIG = MVPConfig(
    as_of_date="2026-05-29",
    compare_to_date="2026-04-30",
    threshold_profile="default",
    horizon_days=20,
    use_llm=USE_LLM,
)

CASE_PACKS = {
    "current_semi": ROOT / "outputs" / "current_semi_unwind",
    "cross_case": ROOT / "outputs" / "cross_case_comparison.md",
}

if CONFIG.use_llm:
    _load_dotenv_if_present()
    evidence_interpreter = DeepSeekEvidenceInterpreter()
    pm_interpreter = DeepSeekPMResponseInterpreter()
else:
    evidence_interpreter = None
    pm_interpreter = None


def fmt(value, signed=False):
    if value is None or value is pd.NA:
        return "unavailable"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return "unavailable"
        return f"{value:+.4f}" if signed else f"{value:.4f}"
    return str(value)


def section(title, text):
    pattern = rf"## {re.escape(title)}\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, flags=re.S)
    return match.group(0).strip() if match else f"_Section not found: {title}_"


def bullets(items):
    return "\n".join(f"- {item}" for item in items) if items else "_None_"
