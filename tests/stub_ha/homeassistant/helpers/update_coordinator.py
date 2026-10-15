class DataUpdateCoordinator:
    def __init__(self,*a,**k): pass
class CoordinatorEntity:
    # Skutečná třída si koordinátor uloží, entity na to spoléhají.
    def __init__(self,coordinator=None,*a,**k): self.coordinator=coordinator
