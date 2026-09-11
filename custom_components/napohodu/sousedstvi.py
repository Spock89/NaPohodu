"""Sousedství zón.

Když se v místnosti spí, je lepší ji vyvětrat cizím oknem než jí foukat
na hlavu. Byt je propojený, takže otevřené kuchyňské okno vymění vzduch
i v ložnici — jen pomaleji a bez průvanu nad postelí.

Podmínky jsou dvě. Musí být otevřené dveře, jinak se vzduch nevymění.
A zastupující zóna nesmí sama vyžadovat klid, jinak se problém jen
přestěhuje o místnost dál.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ZonaStav:
    """Co o zóně potřebujeme vědět, abychom mohli rozdělit práci."""

    id: str
    nazev: str
    co2: float = 450.0
    klid: bool = False           # některá místnost zóny vyžaduje klid
    pod_cilem: bool = False      # větrání by tady stálo teplo
    muze_vetrat: bool = True     # neblokuje ji vítr, zima ani nepřítomnost
    sousedi: list[str] = field(default_factory=list)   # id sousedních zón
    dvere_otevrene: bool = True  # bez otevřených dveří se vzduch nevymění


@dataclass
class Uprava:
    """Co se má se zónou stát po přerozdělení."""

    zastupce: str | None = None   # název zóny, která větrá za nás
    prevzate_co2: float = 0.0     # CO2 zóny, za kterou větráme
    za_koho: list[str] = field(default_factory=list)


def draho(z: ZonaStav) -> bool:
    """Je větrání v téhle zóně drahé?

    Dva různé důvody, stejný důsledek. Když se v ní spí, větrání budí.
    Když je pod cílovou teplotou, větrání stojí teplo a okno pak kmitá
    sem a tam. V obou případech je lepší nechat vyvětrat souseda.
    """
    return z.klid or z.pod_cilem


def prerozdel(zony: list[ZonaStav], prah: float = 1000.0) -> dict[str, Uprava]:
    """Rozhodne, kdo koho zastoupí.

    Vrací úpravu pro každou zónu. Zóna se zástupcem se sama neotevře,
    dokud nejde o krizi. Zastupující zóna dostane cizí CO2, takže se
    otevře dřív, než by musela kvůli sobě.

    Práh má odpovídat tomu, od kterého by se zóna sama otevřela —
    předává ho koordinátor podle nastavení místností.
    """
    podle_id = {z.id: z for z in zony}
    vysledek = {z.id: Uprava() for z in zony}

    for z in zony:
        if not draho(z) or z.co2 <= prah:
            continue          # buď je větrání levné, nebo není proč

        for sid in z.sousedi:
            soused = podle_id.get(sid)
            if soused is None or soused.id == z.id:
                continue
            if draho(soused):
                continue      # tam by to stálo totéž, nepomůže
            if not soused.muze_vetrat:
                continue      # sám nemůže, třeba kvůli větru
            if not (z.dvere_otevrene and soused.dvere_otevrene):
                continue      # zavřené dveře vzduch nepustí

            vysledek[z.id].zastupce = soused.nazev
            u = vysledek[soused.id]
            u.prevzate_co2 = max(u.prevzate_co2, z.co2)
            u.za_koho.append(z.nazev)
            break             # stačí jeden zástupce

    return vysledek
