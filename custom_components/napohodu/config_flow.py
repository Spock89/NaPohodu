"""Konfigurační dialogy integrace Pohoda.

Všechno se nastavuje v UI. Do configuration.yaml se nesahá.

Hlavní záznam drží společné věci — venkovní čidla, počasí, přítomnost.
Místnosti a zóny se přidávají jako podentity tlačítkem, takže jich může
být libovolně a dají se kdykoli upravit bez restartu.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow

try:  # podentity přibyly v HA 2025.2
    from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
    PODENTITY = True
except ImportError:  # pragma: no cover - starší Home Assistant
    ConfigSubentryFlow = object  # type: ignore[assignment, misc]
    SubentryFlowResult = dict  # type: ignore[assignment, misc]
    PODENTITY = False
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import const as c

# ---------------------------------------------------------------- selektory


def _ent(domeny: list[str], vic: bool = False, trida: list[str] | None = None):
    kw: dict[str, Any] = {"domain": domeny, "multiple": vic}
    if trida:
        kw["device_class"] = trida
    return selector.EntitySelector(selector.EntitySelectorConfig(**kw))


def _cislo(min_: float, max_: float, krok: float = 0.5, jednotka: str = "°C"):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_, max=max_, step=krok,
            unit_of_measurement=jednotka,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _volba(moznosti: list[str], klic: str):
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=moznosti,
            translation_key=klic,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


# ---------------------------------------------------------------- hlavní

SCHEMA_GLOBAL = vol.Schema(
    {
        vol.Required(c.CONF_T_VENKU): _ent(["sensor"], trida=["temperature"]),
        vol.Optional(c.CONF_T_PRUMER): _ent(["sensor"], trida=["temperature"]),
        vol.Optional(c.CONF_T_SEZONA): _ent(["sensor"], trida=["temperature"]),
        vol.Optional(c.CONF_SEZONA_PRAH, default=15.0): _cislo(8, 22),
        vol.Optional(c.CONF_SEZONA_HYSTEREZE, default=1.0): _cislo(0, 5, 0.5),
        vol.Optional(c.CONF_RH_VENKU): _ent(["sensor"], trida=["humidity"]),
        vol.Optional(c.CONF_ZARENI): _ent(["sensor"]),
        vol.Optional(c.CONF_VITR): _ent(["sensor"]),
        vol.Optional(c.CONF_NARAZ): _ent(["sensor"]),
        vol.Optional(c.CONF_DEST): _ent(["sensor"]),
        vol.Optional(c.CONF_DOMA): _ent(["input_boolean", "binary_sensor", "person"]),
        vol.Optional(c.CONF_CIL_MIN, default=20.0): _cislo(15, 24),
        vol.Optional(c.CONF_CIL_MAX, default=27.0): _cislo(22, 32),
        vol.Optional(c.CONF_NOC_OD, default="22:00:00"): selector.TimeSelector(),
        vol.Optional(c.CONF_NOC_DO, default="06:30:00"): selector.TimeSelector(),
        vol.Optional(c.CONF_ZPRAVY): _ent(["notify"], True),
        vol.Optional(c.CONF_ZPRAVY_DRUHY,
                     default=["vitr", "dest", "chyba", "souhrn"]):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=c.DRUHY_ZPRAV, multiple=True,
                translation_key="zpravy_druhy",
                mode=selector.SelectSelectorMode.LIST)),
        vol.Optional(c.CONF_SOUHRN_CAS, default="21:00:00"):
            selector.TimeSelector(),
        vol.Optional(c.CONF_VITR_PRAH, default=7.0): _cislo(3, 30, 0.5, "m/s"),
        vol.Optional(c.CONF_NARAZ_PRAH, default=11.0): _cislo(3, 40, 0.5, "m/s"),
        vol.Optional(c.CONF_VITR_KLID, default=5.0): _cislo(2, 25, 0.5, "m/s"),
    }
)


class NaPohoduConfigFlow(ConfigFlow, domain=c.DOMAIN):
    """Založení integrace. Jen jednou, zbytek jsou podentity."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        await self.async_set_unique_id(c.DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="NaPohodu", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SCHEMA_GLOBAL)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, entry: ConfigEntry) -> dict:
        if not PODENTITY:
            return {}
        return {
            c.PODENTITA_MISTNOST: MistnostSubentryFlow,
            c.PODENTITA_ZONA: ZonaSubentryFlow,
            c.PODENTITA_KLIMA: KlimaSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return NaPohoduOptionsFlow()


SCHEMA_TESTER = vol.Schema(
    {
        vol.Required(c.CONF_ZALUZIE): _ent(["cover"]),
        vol.Required(c.CONF_SEKVENCE): selector.TextSelector(),
        vol.Optional(c.CONF_TIMEOUT, default=30): _cislo(5, 180, 5, "s"),
    }
)

SCHEMA_STAVY_VYBER = vol.Schema(
    {vol.Required(c.CONF_ZALUZIE): _ent(["cover"])}
)

SCHEMA_STAVY_TEXT = vol.Schema(
    {
        vol.Optional(c.CONF_STAVY_TEXT, default=""): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
    }
)

SCHEMA_ULOZENI = vol.Schema(
    {
        vol.Optional(c.CONF_NAZEV_STAVU): selector.TextSelector(),
    }
)


class NaPohoduOptionsFlow(OptionsFlow):
    """Společná nastavení a tester žaluzií."""

    def __init__(self) -> None:
        self._tester: dict[str, Any] = {}
        self._vysledek: dict[str, Any] = {}
        self._zaluzie: str = ""
        self._chyba: str = ""

    async def async_step_init(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["nastaveni", "tester", "stavy", "karta"]
        )

    async def async_step_nastaveni(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="nastaveni",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_GLOBAL,
                {**self.config_entry.data, **self.config_entry.options},
            ),
        )

    # ------------------------------------------------------------ karta

    async def async_step_karta(self, user_input=None) -> FlowResult:
        """Vypíše hotovou kartu na dashboard.

        Text je v poli, ze kterého se dá vybrat a zkopírovat. Vkládat ho
        za uživatele nechceme — dashboard si kreslí sám a přepsat mu ho
        by bylo drzé.
        """
        if user_input is not None:
            return await self.async_step_init()

        from unicodedata import normalize

        from . import karty

        def klic(nazev: str) -> str:
            bez = normalize("NFKD", nazev).encode("ascii", "ignore").decode()
            return "".join(z if z.isalnum() else "_"
                           for z in bez.lower()).strip("_")

        mistnosti, oblasti = [], []
        cidla, zaluzie = {}, {}
        s_okny, s_klidem = set(), set()
        for pod in self.config_entry.subentries.values():
            if pod.subentry_type == c.PODENTITA_MISTNOST:
                k = klic(pod.title)
                mistnosti.append(k)
                teploty = pod.data.get(c.CONF_TEPLOTY) or []
                if teploty:
                    cidla[k] = teploty[0]
                zaluzie[k] = (pod.data.get(c.CONF_ZALUZIE)
                              or pod.data.get(c.CONF_ZALUZIE_STARE) or [])
                if pod.data.get(c.CONF_OKNA):
                    s_okny.add(k)
                # klid má smysl jen tam, kde ho něco spouští
                zdroj = pod.data.get(c.CONF_ZDROJ_KLIDU, "spanek")
                ma_spanek = bool(pod.data.get(c.CONF_SPANEK))
                if zdroj == "noc" or (zdroj != "zadny" and ma_spanek):
                    s_klidem.add(k)
            elif pod.subentry_type == c.PODENTITA_ZONA:
                oblasti.append(klic(pod.title))

        g = {**self.config_entry.data, **self.config_entry.options}
        text = karty.dashboard(
            mistnosti, oblasti,
            lambda e: self.hass.states.get(e) is not None,
            cidla=cidla, zaluzie=zaluzie, venku=g.get(c.CONF_T_VENKU),
            s_okny=s_okny, s_klidem=s_klidem)

        return self.async_show_form(
            step_id="karta",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({
                    vol.Optional(c.CONF_KARTA_YAML, default=""):
                        selector.TextSelector(
                            selector.TextSelectorConfig(multiline=True)),
                }),
                {c.CONF_KARTA_YAML: text},
            ),
            description_placeholders={
                "pocet": str(len(mistnosti)),
                "oblasti": str(len(oblasti)),
            },
        )

    # ------------------------------------------------------------ stavy

    async def async_step_stavy(self, user_input=None) -> FlowResult:
        """Výběr žaluzie, jejíž stavy se budou upravovat."""
        if user_input is not None:
            self._zaluzie = user_input[c.CONF_ZALUZIE]
            return await self.async_step_stavy_text()
        return self.async_show_form(
            step_id="stavy", data_schema=SCHEMA_STAVY_VYBER
        )

    async def async_step_stavy_text(self, user_input=None) -> FlowResult:
        """Všechny stavy jedné žaluzie jako text, po řádcích."""
        from .services import nacti_stavy, uloz_hromadne
        from . import sekvence as sq

        chyby = {}
        if user_input is not None:
            vysledek = await uloz_hromadne(
                self.hass, self._zaluzie, user_input.get(c.CONF_STAVY_TEXT, "")
            )
            if vysledek.get("povedlo_se"):
                return await self.async_step_init()
            chyby["base"] = "sekvence"
            self._chyba = vysledek.get("chyba", "")

        text = user_input.get(c.CONF_STAVY_TEXT) if user_input else \
            sq.do_textu(nacti_stavy(self.hass, self._zaluzie))

        return self.async_show_form(
            step_id="stavy_text",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_STAVY_TEXT, {c.CONF_STAVY_TEXT: text}
            ),
            errors=chyby,
            description_placeholders={
                "zaluzie": self._zaluzie,
                "chyba": getattr(self, "_chyba", ""),
            },
        )

    # ------------------------------------------------------------ tester

    async def async_step_tester(self, user_input=None) -> FlowResult:
        """Vyzkouší posloupnost na skutečné žaluzii a ukáže, co se stalo."""
        if user_input is not None:
            self._tester = dict(user_input)
            from .services import proved_sekvenci

            self._vysledek = await proved_sekvenci(
                self.hass,
                user_input[c.CONF_ZALUZIE],
                user_input[c.CONF_SEKVENCE],
                float(user_input.get(c.CONF_TIMEOUT, 30)),
            )
            return await self.async_step_vysledek()

        return self.async_show_form(
            step_id="tester",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_TESTER, self._tester
            ),
        )

    async def async_step_vysledek(self, user_input=None) -> FlowResult:
        """Ukáže výsledek a nechá rozhodnout, co dál.

        Uložit jde jen povedený pokus — u chyby by to nemělo smysl.
        """
        v = self._vysledek
        if v.get("povedlo_se"):
            volby = ["ulozit", "znovu", "hotovo"]
        else:
            volby = ["znovu", "hotovo"]

        return self.async_show_menu(
            step_id="vysledek",
            menu_options=volby,
            description_placeholders={"shrnuti": self._shrnuti()},
        )

    def _shrnuti(self) -> str:
        v = self._vysledek
        if not v.get("povedlo_se"):
            return f"Nepovedlo se: {v.get('chyba')}"
        return (
            f"Hotovo za {v.get('trvani_s')} s.\n\n"
            f"Poloha před: {v.get('poloha_pred')} %\n"
            f"Poloha po: {v.get('poloha_po')} %\n"
            f"Provedeno: {', '.join(v.get('provedeno') or [])}\n\n"
            f"Podívej se z okna. Když lamely vypadají, jak mají, ulož to."
        )

    async def async_step_znovu(self, user_input=None) -> FlowResult:
        """Zpět na tester s předvyplněnou posloupností."""
        return await self.async_step_tester()

    async def async_step_hotovo(self, user_input=None) -> FlowResult:
        return await self.async_step_init()

    async def async_step_ulozit(self, user_input=None) -> FlowResult:
        if user_input is not None:
            nazev = (user_input.get(c.CONF_NAZEV_STAVU) or "").strip()
            if nazev:
                from .services import uloz_stav_stineni

                await uloz_stav_stineni(
                    self.hass, self._tester[c.CONF_ZALUZIE], nazev,
                    self._vysledek.get("sekvence")
                    or self._tester[c.CONF_SEKVENCE],
                )
                return await self.async_step_init()
        from .services import nacti_stavy

        jmena = list(nacti_stavy(self.hass, self._tester[c.CONF_ZALUZIE]))
        return self.async_show_form(
            step_id="ulozit",
            data_schema=vol.Schema({
                vol.Required(c.CONF_NAZEV_STAVU): _stav_vyber(jmena),
            }),
            description_placeholders={
                "sekvence": self._vysledek.get("sekvence", ""),
            },
        )


# ---------------------------------------------------------------- místnost

def _stav_vyber(nazvy: list[str]):
    """Nabídne už uložené stavy, ale nechá napsat i nový."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sorted(nazvy), custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _schema_mistnost(stavy: list[str] | None = None) -> vol.Schema:
    return vol.Schema(
    {
        vol.Required(c.CONF_NAZEV): selector.TextSelector(),
        vol.Optional(c.CONF_TEPLOTY): _ent(["sensor"], True, ["temperature"]),
        vol.Optional(c.CONF_CO2): _ent(["sensor"], True),
        vol.Optional(c.CONF_PM25): _ent(["sensor"], True),
        vol.Optional(c.CONF_PM10): _ent(["sensor"], True),
        vol.Optional(c.CONF_PM_PLATNY): _ent(["binary_sensor", "switch"]),
        vol.Optional(c.CONF_KVALITA): _ent(["sensor"]),
        vol.Optional(c.CONF_CLIMATE): _ent(["climate"], True),
        vol.Optional(c.CONF_CLIMATE_CHLAZENI): _ent(["climate"], True),
        vol.Optional(c.CONF_CLIMATE_OBOJI): _ent(["climate"], True),
        vol.Optional(c.CONF_TOPIT_UTLUM, default=16.0): _cislo(5, 20),
        vol.Optional(c.CONF_TOPIT_MIMO_SEZONU, default=False):
            selector.BooleanSelector(),
        vol.Optional(c.CONF_ODVZDUSNENI_H, default=24): _cislo(0, 96, 1, "h"),
        vol.Optional(c.CONF_ODVZDUSNENI_T, default=28.0): _cislo(22, 32),
        vol.Optional(c.CONF_ODCHYLKA, default=0.0): _cislo(-3, 3),
        vol.Optional(c.CONF_NOC_MIN, default=18.0): _cislo(14, 24),
        vol.Optional(c.CONF_UTLUM, default=16.0): _cislo(5, 20),
        vol.Optional(c.CONF_KOMFORT_ODSTUP, default=4.0): _cislo(1, 15, 0.5),
        vol.Optional(c.CONF_PRIORITA, default=5.0): _cislo(0, 10, 1, ""),
        vol.Optional(c.CONF_VENTILATOR): _ent(["fan", "switch"], True),
        vol.Optional(c.CONF_CISTICKA): _ent(["fan", "switch", "humidifier"], True),
        vol.Optional(c.CONF_RH_VNITRNI): _ent(["sensor"], trida=["humidity"]),
        vol.Optional(c.CONF_ODTAH): _ent(["fan", "switch"], True),
        vol.Optional(c.CONF_RH_MAX, default=60.0): _cislo(40, 80, 1, "%"),
        vol.Optional(c.CONF_ZVLHCOVAC): _ent(
            ["humidifier", "switch", "fan", "input_boolean"], True),
        vol.Optional(c.CONF_RH_MIN, default=38.0): _cislo(20, 55, 1, "%"),
        vol.Optional(c.CONF_VENTILATOR_SMER, default="ven"): _volba(
            c.SMERY_VENTILACE, "ventilator_smer"
        ),

        # --- okna místnosti ---
        vol.Optional(c.CONF_OKNA): _ent(["cover"], True),
        vol.Optional(c.CONF_PROJEZD_M, default=120): _cislo(10, 600, 10, "s"),
        vol.Optional(c.CONF_MIN_DRZENI, default=20): _cislo(1, 120, 1, "min"),
        vol.Optional(c.CONF_KONTAKT_M): _ent(["binary_sensor"], True),
        vol.Optional(c.CONF_ZDROJ_OKENNIHO_M, default="nase_otevreni"): _volba(
            c.ZDROJ_OKENNIHO, "zdroj_okenniho"),
        vol.Optional(c.CONF_VYNUCENO_M): _ent(
            ["input_boolean", "switch", "binary_sensor"], True),
        vol.Optional(c.CONF_CO2_OTEVRIT, default=800): _cislo(500, 2000, 25, "ppm"),
        vol.Optional(c.CONF_CO2_ZAVRIT, default=700): _cislo(400, 1500, 25, "ppm"),
        vol.Optional(c.CONF_CO2_NOC, default=1000): _cislo(600, 2000, 25, "ppm"),
        vol.Optional(c.CONF_CO2_NOC_KRIZE, default=1250): _cislo(800, 2500, 25, "ppm"),
        vol.Optional(c.CONF_DEST_PRAH, default=0.3): _cislo(0, 20, 0.1, "mm/h"),
        vol.Optional(c.CONF_I_KDYZ_NIKDO, default=False):
            selector.BooleanSelector(),
        vol.Optional(c.CONF_T_VENKU_M): _ent(["sensor"], trida=["temperature"]),
        vol.Optional(c.CONF_RH_VENKU_M): _ent(["sensor"], trida=["humidity"]),

        # --- stínění patří k místnosti, protože slunce svítí do pokoje ---
        vol.Optional(c.CONF_ZALUZIE): _ent(["cover"], True),
        vol.Optional(c.CONF_AZIMUT, default=180): _cislo(0, 359, 1, "°"),
        vol.Optional(c.CONF_PLOCHA, default=1.0): _cislo(0.1, 5, 0.1, ""),
        vol.Optional(c.CONF_STINENI_REZIM, default="vzdy"): _volba(
            c.REZIMY_STINENI, "stineni_rezim"
        ),
        vol.Optional(c.CONF_SOUKROMI_KDY, default="nikdy"): _volba(
            c.SOUKROMI_KDY, "soukromi_kdy"
        ),
        vol.Optional(c.CONF_STINENI_PREDSTIH, default=1.0):
            _cislo(0, 5, 0.5),
        vol.Optional(c.CONF_KLID_STINENI_MIN, default=15):
            _cislo(1, 120, 1, "min"),
    }
)

SCHEMA_PRITOMNOST = vol.Schema(
    {
        vol.Optional(c.CONF_ZDROJ_OBSAZENOSTI, default="vzdy"): _volba(
            ["vzdy", "cidlo", "spanek", "cidlo_nebo_spanek", "nikdy"],
            "zdroj_obsazenosti",
        ),
        vol.Optional(c.CONF_ZDROJ_KLIDU, default="spanek"): _volba(
            ["zadny", "spanek", "noc", "spanek_nebo_noc"], "zdroj_klidu"
        ),
        vol.Optional(c.CONF_SPANEK): _ent(["input_boolean", "binary_sensor"]),
        vol.Optional(c.CONF_PRITOMNOST): _ent(["binary_sensor"]),
        vol.Optional(c.CONF_DOBEH, default=30): _cislo(0, 240, 5, "min"),
        vol.Optional(c.CONF_MAX_STARI, default=6): _cislo(1, 48, 1, "h"),
        vol.Optional(c.CONF_STINENI_PRYC, default="nic"): _volba(
            ["nic", "roztahnout", "zatahnout"], "stineni_pryc"
        ),
    }
)

SCHEMA_INDICIE = vol.Schema(
    {
        vol.Optional(c.CONF_INDICIE_STAV): _ent(
            ["media_player", "light", "switch", "binary_sensor"], True
        ),
        vol.Optional(c.CONF_INDICIE_VYKON): _ent(["sensor"], True),
        vol.Optional(c.CONF_PRAH_VYKONU, default=15.0): _cislo(1, 500, 1, "W"),
        vol.Optional(c.CONF_INDICIE_DOBEH, default=10): _cislo(0, 120, 5, "min"),
    }
)


class MistnostSubentryFlow(ConfigSubentryFlow):
    """Přidání a úprava místnosti. Tři kroky, ať formulář není nekonečný."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._uprava = False        # rozlišuje přidání od úpravy

    def _stavy(self) -> list[str]:
        """Jména stavů uložených u kterékoli žaluzie, pro nabídku."""
        try:
            from .services import vsechna_jmena_stavu

            return vsechna_jmena_stavu(self.hass)
        except Exception:  # pragma: no cover
            return []

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        return await self.async_step_zaklad(user_input)

    async def async_step_zaklad(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_stineni()
        return self.async_show_form(
            step_id="zaklad", data_schema=_schema_mistnost(self._stavy()))

    async def async_step_stineni(self, user_input=None) -> SubentryFlowResult:
        """Ke každé žaluzii se přiřadí, který její stav plní kterou roli.

        Dvě žaluzie v jednom pokoji můžou mít stavy pojmenované jinak,
        proto se nabízejí jen ty, které daná žaluzie skutečně má.
        """
        zaluzie = (self._data.get(c.CONF_ZALUZIE)
                   or self._data.get(c.CONF_ZALUZIE_STARE) or [])
        if not zaluzie:
            self._data.pop(c.CONF_STINENI_MAPA, None)
            return await self._dal()

        if user_input is not None:
            self._data[c.CONF_STINENI_MAPA] = {
                k: v for k, v in user_input.items() if v}
            return await self._dal()

        from .services import nacti_stavy

        pole = {}
        for z in zaluzie:
            jmena = sorted(nacti_stavy(self.hass, z))
            for role, popis in (("zastinit", "zastínit"),
                                ("odstinit", "odclonit"),
                                ("soukromi", "soukromí po setmění"),
                                ("pryc", "nikdo doma")):
                pole[vol.Optional(f"{z}|{role}")] = _stav_vyber(jmena)

        return self.async_show_form(
            step_id="stineni",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(pole), self._data.get(c.CONF_STINENI_MAPA, {})
            ),
            description_placeholders={"zaluzie": ", ".join(zaluzie)},
        )

    async def _dal(self) -> SubentryFlowResult:
        """Po stavech žaluzií: při přidávání pokračuj, při úpravě ulož."""
        if not self._uprava:
            return await self.async_step_pritomnost()
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            data=self._data,
            title=self._data[c.CONF_NAZEV],
        )

    async def async_step_pritomnost(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_indicie()
        return self.async_show_form(
            step_id="pritomnost", data_schema=SCHEMA_PRITOMNOST
        )

    async def async_step_indicie(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title=self._data[c.CONF_NAZEV], data=self._data
            )
        return self.async_show_form(step_id="indicie", data_schema=SCHEMA_INDICIE)

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        self._uprava = True
        if user_input is not None:
            self._data.update(user_input)
            # žaluzie mohly přibýt, takže se projde i krok se stavy
            return await self.async_step_stineni()
        self._data = dict(self._get_reconfigure_subentry().data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema_mistnost(self._stavy())
                .extend(SCHEMA_PRITOMNOST.schema)
                .extend(SCHEMA_INDICIE.schema),
                self._data,
            ),
        )


# ---------------------------------------------------------------- zóna

def _vyber(polozky: list[dict]) -> selector.SelectSelector:
    """Ukazuje jméno, ukládá identifikátor. Přejmenování pak odkaz nerozbije."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=polozky or [],
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _schema_zona(mistnosti: list[dict], sousedi: list[dict] | None = None) -> vol.Schema:
    """Oblast je jen propojení místností. Okna a prahy patří místnostem."""
    return vol.Schema(
        {
            vol.Required(c.CONF_NAZEV): selector.TextSelector(),
            vol.Required(c.CONF_MISTNOSTI): _vyber(mistnosti),
            vol.Optional(c.CONF_SOUSEDI): _vyber(sousedi or []),
            vol.Optional(c.CONF_DVERE): _ent(["binary_sensor"], True),
        }
    )


class ZonaSubentryFlow(ConfigSubentryFlow):
    """Zóna je jedno okno a místnosti, které jím dýchají."""

    def _seznam(self, typ: str, krome: str | None = None) -> list[dict]:
        try:
            entry = self._get_entry()
        except Exception:  # pragma: no cover - starší API
            return []
        return [{"value": p.subentry_id, "label": p.title}
                for p in entry.subentries.values()
                if p.subentry_type == typ and p.subentry_id != krome]

    def _zony(self) -> list[dict]:
        try:
            sam = self._get_reconfigure_subentry().subentry_id
        except Exception:  # pragma: no cover
            sam = None
        return self._seznam(c.PODENTITA_ZONA, krome=sam)

    def _mistnosti(self) -> list[dict]:
        return self._seznam(c.PODENTITA_MISTNOST)

    def _obsazene(self, krome: str | None = None) -> dict[str, str]:
        """Místnosti, které už patří jiné zóně."""
        try:
            entry = self._get_entry()
        except Exception:  # pragma: no cover
            return {}
        mapa = {}
        for q in entry.subentries.values():
            if q.subentry_type != c.PODENTITA_ZONA or q.subentry_id == krome:
                continue
            for m in (q.data.get(c.CONF_MISTNOSTI) or []):
                mapa[m] = q.title
        return mapa

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        chyby = {}
        if user_input is not None:
            kolize = [m for m in (user_input.get(c.CONF_MISTNOSTI) or [])
                      if m in self._obsazene()]
            if kolize:
                chyby["base"] = "mistnost_uz_ma_zonu"
            else:
                return self.async_create_entry(
                    title=user_input[c.CONF_NAZEV], data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema_zona(self._mistnosti(), self._zony()),
            errors=chyby,
        )

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        pod = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(), pod, data=user_input,
                title=user_input[c.CONF_NAZEV],
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema_zona(self._mistnosti(), self._zony()), pod.data
            ),
        )


# ---------------------------------------------------------------- klima

def _schema_klima(mistnosti: list[dict]) -> vol.Schema:
    """Sdílená klimatizace na celý byt.

    Vnitřní jednotka v každé místnosti sem nepatří — tu zadáš u té
    místnosti a řídí se sama. Tady je jen jednotka, která obsluhuje víc
    místností a musí se rozhodnout, komu vyhoví.
    """
    jmena = [{"value": m["value"], "label": m["label"]} for m in mistnosti]
    return vol.Schema(
        {
            vol.Required(c.CONF_NAZEV): selector.TextSelector(),
            vol.Required(c.CONF_KLIMA_ENTITA): _ent(["climate"]),
            vol.Optional(c.CONF_KLIMA_UMI, default="chlazeni"): _volba(
                c.UMI_KLIMA, "klima_umi"),
            vol.Optional(c.CONF_KLIMA_V_POKOJI): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=jmena, mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(c.CONF_KLIMA_POKOJE): _vyber(jmena),
            vol.Optional(c.CONF_KLIMA_CHLADIT_OD, default=1.0):
                _cislo(0.5, 5, 0.5),
            vol.Optional(c.CONF_KLIMA_TOPIT_OD, default=1.0):
                _cislo(0.5, 5, 0.5),
            vol.Optional(c.CONF_KLIMA_UTLUM_CHLAZENI, default=28.0):
                _cislo(22, 32),
            vol.Optional(c.CONF_KLIMA_UTLUM_TOPENI, default=16.0):
                _cislo(8, 20),
            vol.Optional(c.CONF_KLIMA_SUSIT_OD, default=0):
                _cislo(0, 80, 1, "%"),
            vol.Optional(c.CONF_KLIMA_DLOUHA): _ent(
                ["input_boolean", "switch", "binary_sensor"]),
            vol.Optional(c.CONF_KLIMA_DLOUHA_H, default=24):
                _cislo(2, 168, 1, "h"),
        }
    )


class KlimaSubentryFlow(ConfigSubentryFlow):
    """Přidání a úprava sdílené klimatizace."""

    def _mistnosti(self) -> list[dict]:
        try:
            entry = self._get_entry()
        except Exception:  # pragma: no cover
            return []
        return [{"value": p.subentry_id, "label": p.title}
                for p in entry.subentries.values()
                if p.subentry_type == c.PODENTITA_MISTNOST]

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[c.CONF_NAZEV], data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_schema_klima(self._mistnosti()))

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        pod = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(), pod, data=user_input,
                title=user_input[c.CONF_NAZEV])
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema_klima(self._mistnosti()), pod.data))
