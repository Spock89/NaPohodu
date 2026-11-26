
def entity_id(v): return v
def string(v): return v


def config_entry_only_config_schema(domain):
    """Integrace se nastavuje jen přes rozhraní, v YAML nemá co dělat."""
    def schema(config):
        return config
    return schema
