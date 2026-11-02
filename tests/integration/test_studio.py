"""Execute genuine Studio validator consensus and finalized contract messages."""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


@pytest.mark.integration
def test_real_studio_flow():
    import live_flow
    original = sys.argv
    try:
        sys.argv = ['live_flow.py']
        live_flow.main()
    finally:
        sys.argv = original
