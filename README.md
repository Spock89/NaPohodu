# NaPohodu

Integrace pro Home Assistant, která v každé místnosti udržuje zvolenou
teplotu a kvalitní vzduch. Rozhoduje, kterým prostředkem toho dosáhnout,
a hlídá, aby si topení, větrání a stínění nelezly do cesty.

## Co dělá

- **Adaptivní cílová teplota** podle EN 16798-1. Počítá se z klouzavého
  průměru venkovní teploty za týden, takže se v průběhu roku mění sama.
  Ovládáš jediný posuvník s odchylkou.
- **Větrání podle CO2, prachu a kvality vzduchu** s mrtvými zónami, aby
  okno neposkakovalo. Délka větrání se řídí skutečným ochlazením
  místnosti, ne stopkami.
- **Noční režim** — jedno dlouhé provětrání místo několika krátkých,
  zavření podle teploty, ranní klid.
- **Sluneční zisk po jednotlivých oknech** podle azimutu a polohy slunce,
  korigovaný naměřeným zářením. Stíní se jen okno, na které svítí.
- **Obsazenost z více důkazů** — pohyb, televize, světla, odběr. PIR sám
  nestačí, protože nevidí sedícího člověka a po vybití baterie zamrzne.

## Co nedělá

Neovládá ventily ani nepočítá polohu žaluzií. Na to jsou
[Better Thermostat](https://github.com/KartoffelToby/better_thermostat)
a [Adaptive Cover](https://github.com/basbruss/adaptive-cover). NaPohodu
jim dodá cílovou teplotu a virtuální okenní senzor.

## Instalace přes HACS

1. HACS → tři tečky vpravo nahoře → **Vlastní repozitáře**
2. Vlož adresu tohoto repozitáře, typ **Integrace**
3. Najdi **NaPohodu**, stáhni, restartuj Home Assistant
4. Nastavení → Zařízení a služby → Přidat integraci → NaPohodu

Všechno se nastavuje ve formulářích. Do `configuration.yaml` se nesahá.

## Ladění žaluzií

Nastavení → Zařízení a služby → Pohoda → **Nastavit** → *Tester žaluzií*.

Posloupnost se píše jedním řádkem: `0, 5s, 14, 3s, 12.7`. Číslo je poloha
v procentech, `3s` je čekání, `=5` počká na potvrzení polohy, `stop`
zastaví za jízdy, `tilt 40` naklopí lamely. Když výsledek sedí, uložíš ho
pod jménem a pak vyvoláváš službou `napohodu.nastav_stineni`.

Ve složce `priklady/` je skript, který převede polohy z Node-REDu, a
návod k testeru.

## Stav

Rozpracované. Jádro je hotové a otestované (92 testů), config flow taky.
Koordinátor a entity se teprve píšou, takže integrace zatím nic neovládá.

## Licence

MIT, viz soubor [LICENSE](LICENSE).

## Poděkování

Pohoda nepřebírá kód z jiných projektů, ale některé postupy vznikly
inspirací:

- [Adaptive Cover](https://github.com/basbruss/adaptive-cover) (MIT) —
  kaskáda priorit jako pojmenovaný seznam pravidel místo vnořených
  podmínek.
- [Better Thermostat](https://github.com/KartoffelToby/better_thermostat)
  (AGPL-3.0) — detekce otevřeného okna z poklesu teploty přes
  exponenciální klouzavý průměr.

**Pozor při přispívání:** Better Thermostat je pod AGPL-3.0. Do NaPohody
se z něj nesmí kopírovat kód, jinak by celý projekt musel na AGPL přejít.
Inspirovat se chováním je v pořádku, myšlenky autorské právo nechrání.
