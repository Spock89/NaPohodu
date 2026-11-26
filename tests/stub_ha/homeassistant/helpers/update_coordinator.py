class DataUpdateCoordinator:
    # Skutečné třídy jsou generické (nesou typ dat), takže se musí dát
    # zapsat v hranatých závorkách i tady.
    def __class_getitem__(cls, _polozka): return cls
    def __init__(self,*a,**k): pass
    # Skutečná třída ji má; kdo zapisuje, si ji volá, aby se karta
    # obnovila. V testu stačí, že existuje a dá se počkat.
    async def async_request_refresh(self): self._vyzadano = getattr(self, "_vyzadano", 0) + 1
    def async_update_listeners(self): pass
class CoordinatorEntity:
    def __class_getitem__(cls, _polozka): return cls
    # Skutečná třída si koordinátor uloží, entity na to spoléhají.
    def __init__(self,coordinator=None,*a,**k): self.coordinator=coordinator
    # Volá se po každém kole koordinátoru; entita si tu může přepočítat,
    # co se mění s časem, a zapsat stav.
    def _handle_coordinator_update(self): self.async_write_ha_state()
