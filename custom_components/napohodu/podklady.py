"""Co karta potřebuje vědět o instalaci.

Oddělené od generátoru i od obou cest, kterými se karta vyrábí —
z dialogu nastavení a ze služby. Dřív to byly dvě kopie téhož a tiše
se rozešly.
"""

from __future__ import annotations

from .const import (CONF_CISTICKA, CONF_CLIMATE, CONF_CO2, CONF_MISTNOSTI,
                    CONF_OKNA, CONF_PM25, CONF_PORADI, CONF_RH_VNITRNI,
                    CONF_SPANEK, CONF_TEPLOTY, CONF_ZALUZIE,
                    CONF_ZVLHCOVAC, PODENTITA_MISTNOST, PODENTITA_SCENA,
                    PODENTITA_SKUPINA, PODENTITA_ZONA, klic)


def podklady(podentity, stav=None) -> dict:
    """Co karta potřebuje vědět o instalaci, poskládané z podentit.

    Jedno místo pro obojí cestu, kterou se karta generuje — z dialogu
    nastavení i ze služby. Dokud to byly dvě kopie, rozešly se:
    služba neuměla vybavení místností, takže tatáž instalace dala
    pokaždé jinou kartu.

    `podentity` jsou záznamy s `subentry_type`, `title` a `data`.
    `stav(eid)` vrací stav entity, nebo nic — kvůli hranám ručiček,
    které se berou z běžící integrace.
    """
    out = {
        "mistnosti": [], "oblasti": [], "skupiny": [], "sceny": [],
        "nazvy": {}, "cidla": {}, "co2_cidla": {}, "rh_cidla": {},
        "pm_cidla": {}, "zaluzie": {}, "zvlhcovace": {},
        "se_zvlhcovacem": set(), "s_cistickou": set(), "s_okny": set(),
        "s_klidem": set(), "vybaveni": {}, "prahy": {},
    }
    poradi: dict[str, float] = {}
    zony: list[list[str]] = []
    # Zóna si členy drží identifikátorem podentity, ne jménem — na
    # rozdíl od skupiny. Převod se musí udělat až nakonec, protože
    # pořadí podentit nikdo nezaručuje a zóna může přijít dřív než
    # místnosti, které vyjmenovává.
    podle_id: dict[str, str] = {}

    for pod in podentity:
        if pod.subentry_type == PODENTITA_MISTNOST:
            k = klic(pod.title)
            podle_id[pod.subentry_id] = k
            out["mistnosti"].append(k)
            out["nazvy"][k] = pod.title
            if pod.data.get(CONF_ZVLHCOVAC):
                out["se_zvlhcovacem"].add(k)
                out["zvlhcovace"][k] = list(pod.data[CONF_ZVLHCOVAC])
            if pod.data.get(CONF_CISTICKA):
                out["s_cistickou"].add(k)
            # Co místnost opravdu má. Podle toho se generují jen
            # nastavení, která v ní něco ovlivní.
            znacky = set()
            if pod.data.get(CONF_OKNA):
                znacky |= {"okno", "co2"}
                out["s_okny"].add(k)
            if pod.data.get(CONF_ZALUZIE):
                znacky.add("zaluzie")
            if pod.data.get(CONF_CLIMATE):
                znacky.add("topeni")
            if pod.data.get(CONF_CO2):
                znacky.add("co2")
            if pod.data.get(CONF_PM25) or pod.data.get(CONF_CISTICKA):
                znacky.add("prach")
            out["vybaveni"][k] = znacky
            pm = pod.data.get(CONF_PM25) or []
            if pm:
                out["pm_cidla"][k] = pm[0]
            # Hrany barevných pásem pro ručičky. Berou se z běžící
            # integrace, protože tam se podle nich i rozhoduje —
            # počítat je tady podruhé by znamenalo druhou pravdu,
            # která se jednou rozejde.
            st = stav(f"sensor.napohodu_{k}_stav") if stav else None
            meze = st.attributes.get("pasma_ukazatelu") if st else None
            if meze:
                out["prahy"][k] = dict(meze)
            poradi[k] = float(pod.data.get(CONF_PORADI, 0) or 0)
            teploty = pod.data.get(CONF_TEPLOTY) or []
            if teploty:
                out["cidla"][k] = teploty[0]
            co2 = pod.data.get(CONF_CO2) or []
            if co2:
                out["co2_cidla"][k] = co2[0]
            rh = pod.data.get(CONF_RH_VNITRNI)
            if rh:
                out["rh_cidla"][k] = rh
            out["zaluzie"][k] = pod.data.get(CONF_ZALUZIE) or []
            # klid má smysl jen tam, kde je spánkový přepínač
            if pod.data.get(CONF_SPANEK):
                out["s_klidem"].add(k)
        elif pod.subentry_type == PODENTITA_SKUPINA:
            out["skupiny"].append(pod.title)
        elif pod.subentry_type == PODENTITA_SCENA:
            out["sceny"].append(pod.title)
        elif pod.subentry_type == PODENTITA_ZONA:
            out["nazvy"][klic(pod.title)] = pod.title
            out["oblasti"].append(klic(pod.title))
            zony.append(list(pod.data.get(CONF_MISTNOSTI) or []))

    # Místnost bez okna v zóně, kde nějaké okno je, si o vyvětrání
    # řekne sousedovi — a hranici, od jaké odchylky od cíle, si
    # určuje svým vlastním číslem. Patří jí tedy to šoupátko, i když
    # vlastní okno nemá.
    for cleni in zony:
        # Starší nastavení mají místo identifikátoru jméno, proto se
        # zkusí obojí — stejně jako to dělá koordinátor.
        klice = [podle_id.get(x) or klic(x) for x in cleni]
        if not any(x in out["s_okny"] for x in klice):
            continue
        for x in klice:
            if x in out["vybaveni"] and x not in out["s_okny"]:
                out["vybaveni"][x].add("vetrani_zonou")

    # Pořadí z nastavení, při stejném čísle jak místnosti vznikly.
    puvodni = {k: i for i, k in enumerate(out["mistnosti"])}
    out["mistnosti"].sort(key=lambda k: (poradi.get(k, 0), puvodni[k]))
    return out
