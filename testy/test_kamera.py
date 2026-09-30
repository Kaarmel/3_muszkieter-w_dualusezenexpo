"""Wynik kamery pochodzi z porównania opisów scen, a nie z detektora dronowego."""

import sys
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(KATALOG), str(KATALOG / "symulator")]

from ai.kamera import OPISY, decyzja


assert decyzja([{"label": OPISY["zalany"], "score": 0.8},
                {"label": OPISY["suchy"], "score": 0.2}]) == "zalany"
assert decyzja([{"label": OPISY["suchy"], "score": 0.8},
                {"label": OPISY["zalany"], "score": 0.2}]) == "suchy"
assert decyzja([{"label": OPISY["rzeka"], "score": 0.8},
                {"label": OPISY["zalany"], "score": 0.2}]) == "nieznany"
print("OK: klasyfikacja sceny z kamerki")
