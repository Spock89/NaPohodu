"""Problémy, které si člověk může spravit sám.

Integrace už dřív poznala, že něco nesedí — vlastní entitu přiřazenou
jako hlavici, přiřazení ukazující na smazanou žaluzii, čidlo hlásící
ve Fahrenheitech. Jenže to psala jen do protokolu, kam se nikdo
nepodívá, takže to navenek vypadalo, že integrace nereaguje.

Tady se z toho stane položka v **Nastavení → Opravy**: co se děje,
proč to vadí, co s tím a co se stane potom. Pravidlo Home Assistantu
je, že se zakládají jen problémy, se kterými uživatel opravdu může něco
udělat — hláška, na kterou se nedá reagovat, je jen strašák.

Dvě věci se musely ohlídat:

**Zmizet to musí samo.** Kdo přenastaví čidlo, nemá dál koukat na
hlášku o tom starém. Každý cyklus se proto hlásí znovu všechno, co
pořád platí, a co se neohlásilo, se zruší.

**Nehlásit planý poplach.** Při startu se integrace načítají postupně
a cizí entita se ozve později než my. Chybějící entita se proto hlásí
teprve tehdy, když ji nezná ani registr, a až po několika cyklech po
sobě.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Kolik cyklů po sobě musí entita chybět, než se to ohlásí. Cyklus je
# minuta; tři jsou dost na to, aby doběhl start Home Assistantu, a málo
# na to, aby si toho člověk nevšiml.
NEZ_SE_OHLASI = 3

# Jak vypadá identifikátor entity. Hodnoty v nastavení jsou čísla,
# pravdivostní hodnoty a výběry entit, takže tečka v textu znamená
# entitu — a i kdyby ne, hlásí se jen to, co nezná registr.
ENTITA = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")

ZAVAZNOST = {
    # Psát si sám sobě je chyba zadání, která tiše kazí výsledek.
    "smycka": ir.IssueSeverity.ERROR,
    "chybi": ir.IssueSeverity.WARNING,
    "chybi_byt": ir.IssueSeverity.WARNING,
    "jednotka": ir.IssueSeverity.WARNING,
}


def entity_v_nastaveni(data: Mapping[str, Any] | None) -> set[str]:
    """Všechny entity, na které se nastavení odvolává.

    Hledá se podle tvaru hodnoty, ne podle seznamu polí: ručně psaný
    výčet polí by zastaral při prvním dalším výběru čidla, a právě
    takhle se na přiřazení stínění zapomnělo, protože entity jsou tam
    v klíčích, ne v hodnotách.
    """
    nalez: set[str] = set()

    def projdi(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and ENTITA.match(k):
                    nalez.add(k)
                projdi(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                projdi(v)
        elif isinstance(x, str) and ENTITA.match(x):
            nalez.add(x)

    projdi(data or {})
    return nalez


class Opravy:
    """Účetnictví položek v Opravách: co platí teď a co už ne."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._platne: set[str] = set()
        self._tento_cyklus: set[str] = set()
        # Kolikrát po sobě už entita chyběla.
        self._chybi_kolikrat: dict[str, int] = {}
        # Čidla hlásící v jiné jednotce. Jednotka se kontroluje jen
        # jednou, ale hlásit se musí každý cyklus, jinak by položka
        # hned zmizela.
        self.spatne_jednotky: dict[str, dict[str, str]] = {}

    # --- hlášení ------------------------------------------------------

    def zacni(self) -> None:
        self._tento_cyklus = set()

    def nahlas(self, druh: str, predmet: str, **texty: str) -> None:
        """Tahle položka pořád platí. Víc hlášení = jedna položka.

        `predmet` dělá z druhu problému konkrétní položku, aby se dvě
        chybějící čidla nehlásila jako jedno — a aby se totéž čidlo
        hlásilo pořád jako jedna položka, ne každou minutu znovu.
        """
        klic = f"{druh}_{predmet}"
        self._tento_cyklus.add(klic)
        if klic in self._platne:
            return
        self._platne.add(klic)
        try:
            ir.async_create_issue(
                self.hass, DOMAIN, klic,
                is_fixable=False, severity=ZAVAZNOST[druh],
                translation_key=druh,
                translation_placeholders={k: str(v)
                                          for k, v in texty.items()})
        except Exception as e:      # pragma: no cover - cizí registr
            _LOGGER.debug("NaPohodu: oprava %s se nezaložila: %s", klic, e)

    def hotovo(self) -> None:
        """Zruší položky, které se tento cyklus neohlásily."""
        for klic in sorted(self._platne - self._tento_cyklus):
            self._platne.discard(klic)
            try:
                ir.async_delete_issue(self.hass, DOMAIN, klic)
            except Exception as e:  # pragma: no cover - cizí registr
                _LOGGER.debug("NaPohodu: oprava %s se nezrušila: %s",
                              klic, e)

    # --- jednotlivé druhy ---------------------------------------------

    def jednotka(self, eid: str, popis: str, jednotka: str,
                 ocekavane: str) -> None:
        """Čidlo hlásí v jednotce, se kterou prahy nepočítají."""
        self.spatne_jednotky[eid] = {
            "entita": eid, "popis": popis,
            "jednotka": jednotka, "ocekavane": ocekavane}

    def zkontroluj(self, entry: Any,
                   existuje: Callable[[str], bool]) -> None:
        """Projde celé nastavení a ohlásí, co se v něm nedá najít.

        `existuje` dodává koordinátor a ptá se na stav i na registr
        entit naráz. Jedna strana nestačí: registr nezná čidla z YAML
        bez `unique_id` a stav zase chybí entitě, jejíž integrace se
        ještě nenačetla. Rozdíl mezi „neexistuje" a „zatím mlčí" se
        bez obojího udělat nedá.
        """
        # Kde entita stojí. Prázdné jméno znamená společné nastavení
        # bytu — tam se do nastavení chodí jinou cestou než
        # k místnosti, takže si zaslouží vlastní hlášku; návod, který
        # posílá na „Upravit" u podentity, by v něm neplatil.
        hledane: dict[str, str] = {}
        for e in entity_v_nastaveni({**entry.data, **entry.options}):
            hledane[e] = ""
        for pod in entry.subentries.values():
            for e in entity_v_nastaveni(pod.data):
                hledane.setdefault(e, pod.title)

        for eid, kde in sorted(hledane.items()):
            if existuje(eid):
                self._chybi_kolikrat.pop(eid, None)
                continue
            kolikrat = self._chybi_kolikrat.get(eid, 0) + 1
            self._chybi_kolikrat[eid] = kolikrat
            if kolikrat >= NEZ_SE_OHLASI:
                if kde:
                    self.nahlas("chybi", eid, entita=eid, kde=kde)
                else:
                    self.nahlas("chybi_byt", eid, entita=eid)
        # Entita, která se vrátila nebo se přestala používat, se
        # z počítadla musí ztratit, jinak by po jejím druhém smazání
        # vyskočila hláška hned.
        for eid in list(self._chybi_kolikrat):
            if eid not in hledane:
                self._chybi_kolikrat.pop(eid, None)

        for eid, texty in sorted(self.spatne_jednotky.items()):
            if eid in hledane:
                self.nahlas("jednotka", eid, **texty)
