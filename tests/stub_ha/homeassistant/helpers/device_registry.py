DeviceInfo = dict


class DeviceEntry:
    """Zápis zařízení v registru. Pro náhradu stačí identifikátory."""

    def __init__(self, identifiers=(), name=""):
        self.identifiers = set(identifiers)
        self.name = name
