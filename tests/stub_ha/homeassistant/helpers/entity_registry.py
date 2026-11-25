class RegistrZapis:
    def __init__(self, entity_id, unique_id="", domain=None,
                 platform="cizi", config_entry_id=None):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.domain = domain or entity_id.split(".")[0]
        # Ke kterému zápisu konfigurace entita patří. Registr drží
        # entity všech integrací, takže bez toho se vlastní od cizích
        # neoddělí.
        self.config_entry_id = config_entry_id
        # Která integrace entitu vyrobila. Podle toho se pozná vlastní
        # entita přiřazená jako cizí zařízení.
        self.platform = platform


class Registr:
    def __init__(self, zapisy=()):
        self.zapisy = list(zapisy)
        self.prejmenovane = []
        self.smazane = []

    def async_get_entity_id(self, domain, platform, unique_id):
        for z in self.zapisy:
            if z.unique_id == unique_id and z.domain == domain:
                return z.entity_id
        return None

    def async_get(self, entity_id):
        for z in self.zapisy:
            if z.entity_id == entity_id:
                return z
        return None

    def async_remove(self, entity_id):
        self.smazane.append(entity_id)
        self.zapisy = [z for z in self.zapisy if z.entity_id != entity_id]

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
    return [z for z in registr.zapisy if z.config_entry_id == entry_id]
