class Store:
    """Náhrada úložiště: drží data v paměti po dobu testu."""

    _data = {}

    def __init__(self, hass=None, verze=1, klic="", **k):
        self.klic = klic

    async def async_load(self):
        return Store._data.get(self.klic)

    async def async_save(self, data):
        Store._data[self.klic] = data

    def async_delay_save(self, funkce, zpozdeni=0):
        """Odložené uložení. V testu se ukládá rovnou."""
        Store._data[self.klic] = funkce()
