class DataUpdateCoordinator:
    def __init__(self,*a,**k): pass
    # Skutečná třída ji má; kdo zapisuje, si ji volá, aby se karta
    # obnovila. V testu stačí, že existuje a dá se počkat.
    async def async_request_refresh(self): self._vyzadano = getattr(self, "_vyzadano", 0) + 1
    def async_update_listeners(self): pass
class CoordinatorEntity:
    # Skutečná třída si koordinátor uloží, entity na to spoléhají.
    def __init__(self,coordinator=None,*a,**k): self.coordinator=coordinator
