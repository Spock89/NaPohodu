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

from .const import CONF_ZALUZIE, CONF_ZALUZIE_STARE, PODENTITA_MISTNOST

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
    """Srovná starší jména entit a klíčů. Smí se spustit opakovaně."""
    _jmena_entit(hass, entry)
    await _klic_zaluzii(hass, entry)


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
                _LOGGER.warning(
                    "NaPohodu: %s by se mělo jmenovat %s, ale to už "
                    "existuje — přejmenuj jedno z nich ručně",
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
