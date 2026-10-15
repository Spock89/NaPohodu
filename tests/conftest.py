"""Testy běží proti modulům uvnitř integrace, ne proti kopii.

Cesta se připojuje na konec, ne na začátek: balíček má moduly
`datetime.py` a `select.py`, které se jmenují stejně jako standardní
knihovna. Na začátku cesty by je zastínily a rozbily všechno, co
s časem pracuje — v Home Assistantu se importují jako součást balíčku,
takže tam ke kolizi nedochází.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent
                    / "custom_components" / "napohodu"))
