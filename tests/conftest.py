import sys
from pathlib import Path

# Tests laufen ohne installiertes Paket: src/ direkt importierbar machen.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
