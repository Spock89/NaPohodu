class RegistrZapis:
    def __init__(self, entity_id, unique_id="", domain=None):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.domain = domain or entity_id.split(".")[0]


class Registr:
    def __init__(self, zapisy=()):
        self.zapisy = list(zapisy)
        self.prejmenovane = []

    def async_get(self, entity_id):
        for z in self.zapisy:
            if z.entity_id == entity_id:
                return z
        return None

    def async_update_entity(self, entity_id, new_entity_id=None, **_k):
        for z in self.zapisy:
            if z.entity_id == entity_id:
                self.prejmenovane.append((entity_id, new_entity_id))
                z.entity_id = new_entity_id or entity_id
                return z
        return None


_registr = Registr()


def async_get(hass):
    return getattr(hass, "registr", None) or _registr


def async_entries_for_config_entry(registr, entry_id):
    return list(registr.zapisy)
