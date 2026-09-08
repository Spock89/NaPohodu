"""Testy běží proti modulům uvnitř integrace, ne proti kopii."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent
                       / "custom_components" / "napohodu"))
