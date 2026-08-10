import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SERVICES_SRC = Path(__file__).resolve().parent.parent / "src"
if str(SERVICES_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICES_SRC))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _decimalize(obj):
    """Mirror pollen_api.fetch_forecast's parse_float=Decimal so fixtures match real payloads."""
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(v) for v in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


@pytest.fixture
def sample_forecast_payload():
    """A trimmed but real forecast:lookup response, recorded via scripts/fetch_pollen_sample.py."""
    raw = json.loads((FIXTURES_DIR / "sample_forecast.json").read_text())
    return _decimalize(raw)
