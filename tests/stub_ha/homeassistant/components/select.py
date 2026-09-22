class SelectEntity:
    _attr_options: list = []
    _attr_current_option = None
    _attr_translation_placeholders: dict = {}

    def async_write_ha_state(self):
        pass
