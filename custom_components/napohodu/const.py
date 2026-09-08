"""Konstanty integrace NaPohodu."""

DOMAIN = "napohodu"

PODENTITA_MISTNOST = "mistnost"
PODENTITA_ZONA = "zona"

# --- globální nastavení ---
CONF_T_VENKU = "t_venku"
CONF_T_PRUMER = "t_prumer"          # týdenní průměr pro adaptivní cíl
CONF_T_SEZONA = "t_sezona"          # třídenní průměr pro topnou sezónu
CONF_SEZONA_PRAH = "sezona_prah"
CONF_SEZONA_HYSTEREZE = "sezona_hystereze"
CONF_RH_VENKU = "rh_venku"
CONF_ZARENI = "zareni"
CONF_VITR = "vitr"
CONF_NARAZ = "naraz_vetru"
CONF_DEST = "dest"
CONF_DOMA = "doma"
CONF_POSUN = "posun"
CONF_CIL_MIN = "cil_min"
CONF_CIL_MAX = "cil_max"
CONF_NOC_OD = "noc_od"
CONF_NOC_DO = "noc_do"
CONF_VITR_PRAH = "vitr_prah"
CONF_VITR_KLID = "vitr_klid"

# --- místnost ---
CONF_NAZEV = "nazev"
CONF_TEPLOTY = "teploty"
CONF_VENTILATORY = "ventilatory"
CONF_CO2 = "co2"
CONF_PM25 = "pm25"
CONF_PM10 = "pm10"
CONF_PM_PLATNY = "pm_platny"
CONF_KVALITA = "kvalita"
CONF_SPANEK = "spanek"
CONF_PRITOMNOST = "pritomnost"
CONF_ZDROJ_OBSAZENOSTI = "zdroj_obsazenosti"
CONF_ZDROJ_KLIDU = "zdroj_klidu"
CONF_DOBEH = "dobeh_min"
CONF_MAX_STARI = "max_stari_h"
CONF_CLIMATE = "climate"                 # radiátory, jen topí
CONF_CLIMATE_CHLAZENI = "climate_chlazeni"   # jen chladí
CONF_CLIMATE_OBOJI = "climate_oboji"         # tepelné čerpadlo, topí i chladí
CONF_UTLUM = "utlum"
CONF_ODCHYLKA = "odchylka"
CONF_NOC_MIN = "noc_min"
CONF_STINENI_PRYC = "stineni_pryc"
CONF_KOMFORT_ODSTUP = "komfort_odstup"
CONF_PRIORITA = "priorita_vzduchu"

# nucená ventilace (ventilátor, rekuperace)
CONF_CISTICKA = "cisticka"
CONF_ODTAH = "odtah"
CONF_RH_VNITRNI = "rh_vnitrni"
CONF_RH_MAX = "rh_max"
CONF_VENTILATOR = "ventilator"
CONF_VENTILATOR_SMER = "ventilator_smer"
SMERY_VENTILACE = ["ven", "dovnitr", "oboji"]

# indicie obsazenosti
CONF_INDICIE_STAV = "indicie_stav"      # entity, kde "on"/"playing" = obsazeno
CONF_INDICIE_VYKON = "indicie_vykon"    # číselné entity s prahem
CONF_PRAH_VYKONU = "prah_vykonu"
CONF_INDICIE_DOBEH = "indicie_dobeh_min"

# --- zóna ---
CONF_OKNO = "okno"
CONF_PROJEZD = "projezd_s"
CONF_MISTNOSTI = "mistnosti"
CONF_SOUSEDI = "sousedi"
CONF_DVERE = "dvere"
CONF_KONTAKT = "kontakt"
CONF_ZDROJ_OKENNIHO = "zdroj_okenniho_senzoru"
CONF_VYNUCENO = "vynuceno"
CONF_CO2_OTEVRIT = "co2_otevrit"
CONF_CO2_ZAVRIT = "co2_zavrit"

# stínění zóny: jména uložených stavů
CONF_ZALUZIE_ZONY = "zaluzie_zony"
CONF_STINENI_MAPA = "stineni_mapa"   # {"cover.o1|zastinit": "zastíněno"}
CONF_KLID_STINENI_MIN = "klid_stineni_min"
CONF_STINENI_REZIM = "stineni_rezim"
CONF_SOUKROMI_KDY = "soukromi_kdy"
REZIMY_STINENI = ["vzdy", "jen_pryc", "nikdy"]
SOUKROMI_KDY = ["nikdy", "hned", "pri_pohybu"]

# --- okna pro sluneční zisk ---
CONF_AZIMUT = "azimut"
CONF_PLOCHA = "plocha"
CONF_ZORNE_POLE = "zorne_pole"

ZDROJ_OKENNIHO = ["fyzicke", "nase_otevreni", "oboji", "nikdy"]

# tester žaluzií
CONF_ZALUZIE = "zaluzie"
CONF_SEKVENCE = "sekvence"
CONF_TIMEOUT = "timeout_polohy_s"
CONF_NAZEV_STAVU = "nazev_stavu"
CONF_STAVY_TEXT = "stavy_text"

INTERVAL_S = 60
