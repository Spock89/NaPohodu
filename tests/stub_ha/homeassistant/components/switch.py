class SwitchEntity:
    # Skutečný Home Assistant čte jméno z `_attr_name`, a `name` je
    # u něj `cached_property`. Náhrada to musí dělat stejně, jinak
    # projde i kód, který si `name` přepíše vlastností — a tomu HA
    # jméno nedostane a karta spadne na jméno zařízení.
    @property
    def name(self):
        return getattr(self, "_attr_name", None)
