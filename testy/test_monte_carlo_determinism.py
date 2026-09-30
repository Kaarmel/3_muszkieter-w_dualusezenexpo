"""Ten sam scenariusz musi dawać te same czasy niezależnie od kolejności zbiorów Pythona."""

import os
import subprocess
import sys

SKRYPT = """import random,sys
sys.path.insert(0, 'planer')
import monte_carlo as m, scenariusz as s
w = m.Swiat()
p = s.losuj_prawde(w.odc, random.Random(1000))
for strategia in ('A', 'B'):
    krzywa, _ = m.symuluj(w, p, strategia, drony=4)
    print(krzywa)
"""


if __name__ == "__main__":
    def wynik(ziarno):
        return subprocess.check_output(
            [sys.executable, "-c", SKRYPT],
            env={**os.environ, "PYTHONHASHSEED": ziarno}, text=True,
        )

    assert wynik("0") == wynik("1"), "Monte Carlo zależy od PYTHONHASHSEED"
    print("OK: Monte Carlo jest powtarzalne")
