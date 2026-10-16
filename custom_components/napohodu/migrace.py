"""Jednorázové srovnání starší konfigurace při načtení integrace.

Starší podoby jmen a klíčů se dřív dotahovaly při každém čtení: karta
zkoušela postupně všechny identifikátory, pod kterými kdy šoupátko
vzniklo, a koordinátor sahal po starém klíči, když nový nebyl vyplněný.
Fungovalo to, ale znamenalo to nést minulost v každém rozhodnutí
a pamatovat na ni při každé úpravě.

Tady se to srovná **jednou**, při načtení integrace, a dál už se
pracuje jen s dnešními jmény:

* entita, která si drží identifikátor po přejmenovaném šoupátku, se
  v registru přepíše na dnešní,
* seznam žaluzií uložený pod dřívějším klíčem se přepíše do dnešního.

Každá změna se vypíše do logu — kdo má v automatizaci starý
identifikátor, musí ho opravit, a bez záznamu by se to nedalo dohledat.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (CONF_ZALUZIE, CONF_ZALUZIE_STARE, DOMAIN,
                    PODENTITA_MISTNOST)

_LOGGER = logging.getLogger(__name__)

# Identifikátor entity vzniká z přeloženého jména a Home Assistant ho
# při přejmenování nemění. Instalace, která šoupátko založila pod
# dřívějším jménem, ho tedy má pořád pod ním. Klíč je starý konec
# identifikátoru, hodnota dnešní.
STARSI_JMENA = {
    # pásmo nahradilo denní hysterezi a noční mez
    "denni_hystereze": "ve_dne_otevrit_pri_odchylce_od_cile_o",
    "odstup_od_cile_pro_otevreni": "ve_dne_otevrit_pri_odchylce_od_cile_o",
    "ve_dne_smi_klesnout_pod_cil_o": "ve_dne_otevrit_pri_odchylce_od_cile_o",
    "v_noci_vychladnout_nejvys_na": "pojistka_nevychladit_pod",
    "minimum_na_noc": "pojistka_nevychladit_pod",
    "odchylka_teploty": "moje_odchylka_teploty",
    "v_noci_topit_o_mene": "v_noci_posun_cilove_teploty",
    "nocni_utlum_topeni": "v_noci_posun_cilove_teploty",
    "utlum_pri_otevrenem_okne": "pri_otevrenem_okne_topit_na",
    "v_noci_otevrit_nad": "v_noci_otevrit_nad_co2",
    "nouzove_otevrit_nad": "nouzove_otevrit_nad_co2",
}


async def srovnej(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Srovná starší jména entit a klíčů.

    Proběhne **jednou za instalaci**. Integrace se načítá znovu při
    každé změně nastavení a změna, kterou srovnání samo udělá, další
    načtení spustit může — bez téhle pojistky by se celé kolo mohlo
    opakovat pořád dokola a log by zaplavilo jedno hlášení.

    Poznámka se proto zapisuje **napřed**, ne až po práci. Když se
    mezitím něco pokazí, zbude nanejvýš nesrovnaný řádek v registru:
    to je kosmetická vada, kdežto nekonečné kolo načítání je porucha.
    Spustit znovu jde službou `napohodu.srovnej_jmena`.
    """
    uloziste = Store(hass, 1, f"{DOMAIN}.migrace")
    try:
        hotovo = await uloziste.async_load()
    except Exception:      # pragma: no cover - poškozený soubor
        hotovo = None
    if (hotovo or {}).get("srovnano"):
        return
    try:
        await uloziste.async_save({"srovnano": True})
    except Exception as e:      # pragma: no cover - zápis se nepovedl
        _LOGGER.warning("NaPohodu: poznámku o srovnání se nepodařilo "
                        "uložit (%s), příště se zopakuje", e)
    await znovu(hass, entry)


async def znovu(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Samotná práce. Volá se při prvním načtení a ze služby.

    Každý krok si hlídá svoje chyby: srovnání jmen je úklid, ne
    podmínka chodu, a shodit kvůli němu načtení integrace by bylo
    nepoměrné.
    """
    # Nejdřív zbytky, pak jména: entita po zrušeném nastavení nemá
    # smysl přejmenovávat a zároveň by blokovala jméno té živé.
    for krok in (_zbytky, _jmena_entit):
        try:
            krok(hass, entry)
        except Exception as e:      # pragma: no cover - cizí rozhraní
            _LOGGER.error("NaPohodu: srovnání %s selhalo: %s",
                          krok.__name__.strip("_"), e)
    try:
        await _klic_zaluzii(hass, entry)
    except Exception as e:      # pragma: no cover - cizí rozhraní
        _LOGGER.error("NaPohodu: srovnání klíče žaluzií selhalo: %s", e)


def _zbytky(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Smaže šoupátka po nastavení, které už neexistuje.

    Entita se pozná podle trvalého identifikátoru složeného z místnosti
    a klíče nastavení. Když se nastavení zrušilo nebo přejmenovalo,
    zůstane v registru řádek, který už nikdo nevyrobí: hlásí se jako
    nedostupný, ručně ho smazat nejde a blokuje jméno tomu živému.

    Maže se jen mezi šoupátky a jen to, co se z dnešní konfigurace
    nemá jak vyrobit — tedy nikdy nic, co by příští načtení založilo
    znovu.
    """
    from .number import CELY_BYT, MISTNOST

    ziva = {f"{entry.entry_id}_{p.klic}" for p in CELY_BYT}
    for pod in entry.subentries.values():
        if pod.subentry_type == PODENTITA_MISTNOST:
            ziva |= {f"{pod.subentry_id}_{p.klic}" for p in MISTNOST}

    registr = er.async_get(hass)
    for zapis in list(er.async_entries_for_config_entry(registr,
                                                        entry.entry_id)):
        if zapis.domain != "number" or zapis.unique_id in ziva:
            continue
        registr.async_remove(zapis.entity_id)
        _LOGGER.warning(
            "NaPohodu: %s smazáno — zbytek po nastavení, které už "
            "neexistuje. Hlásilo se jako nedostupné a ručně smazat "
            "nešlo.", zapis.entity_id)


def _jmena_entit(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Přepíše identifikátory po přejmenovaných šoupátkách.

    Přepisuje se jen to, co se jmenuje jako některé z našich
    dřívějších jmen — vlastní jméno, které si někdo nastavil sám,
    zůstane. Obsazený cílový identifikátor se přeskočí: dvě entity
    na jedno jméno nejdou a hádat příponu by vedlo k další podivnosti.
    """
    registr = er.async_get(hass)
    dnesni = set(STARSI_JMENA.values())
    for zapis in er.async_entries_for_config_entry(registr, entry.entry_id):
        if zapis.domain != "number":
            continue
        # Dnešní jméno může končit stejně jako to dřívější —
        # „moje_odchylka_teploty" končí na „odchylka_teploty". Kdo už
        # je pojmenovaný správně, se proto nechá být; jinak by z něj
        # při každém načtení přibylo další „moje_".
        if any(zapis.entity_id.endswith(f"_{x}") for x in dnesni):
            continue
        for stare, nove in STARSI_JMENA.items():
            if not zapis.entity_id.endswith(f"_{stare}"):
                continue
            cil = zapis.entity_id[: -len(stare)] + nove
            if registr.async_get(cil) is not None:
                # Obě jména v registru znamenají, že to živé šoupátko
                # je pod dnešním jménem a tohle je po něm zbytek.
                # Smazat ho za člověka nejde: jistotu, která z nich je
                # ta pravá, odsud nemáme.
                _LOGGER.warning(
                    "NaPohodu: %s je zbytek po dřívějším jméně — "
                    "šoupátko už existuje jako %s. Tu starou entitu "
                    "můžeš smazat v Nastavení → Zařízení a služby → "
                    "Entity; nic se tím nerozbije.",
                    zapis.entity_id, cil)
                break
            registr.async_update_entity(zapis.entity_id, new_entity_id=cil)
            _LOGGER.warning(
                "NaPohodu: %s přejmenováno na %s (dřívější název "
                "šoupátka). Máš-li ten starý v automatizaci nebo ve "
                "vlastní kartě, oprav ho.", zapis.entity_id, cil)
            break


async def _klic_zaluzii(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Přepíše seznam žaluzií z dřívějšího klíče do dnešního."""
    for pod in list(entry.subentries.values()):
        if pod.subentry_type != PODENTITA_MISTNOST:
            continue
        stare = pod.data.get(CONF_ZALUZIE_STARE)
        if not stare or pod.data.get(CONF_ZALUZIE):
            continue
        data = {k: v for k, v in pod.data.items() if k != CONF_ZALUZIE_STARE}
        data[CONF_ZALUZIE] = stare
        try:
            hass.config_entries.async_update_subentry(entry, pod, data=data)
        except Exception as e:      # pragma: no cover - cizí rozhraní
            # Bez tohohle by místnost o žaluziích nevěděla, a to se
            # musí dozvědět člověk, ne jen log na úrovni debug.
            _LOGGER.error(
                "NaPohodu: %s má žaluzie uložené pod dřívějším klíčem "
                "a přepsat se je nepodařilo (%s). Otevři nastavení té "
                "místnosti a ulož ho znovu.", pod.title, e)
            continue
        _LOGGER.info("NaPohodu: %s — seznam žaluzií srovnán", pod.title)
