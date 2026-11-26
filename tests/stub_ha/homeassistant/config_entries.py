
class ConfigEntry:
    # Home Assistant má ConfigEntry generický, aby se dal typovat
    # runtime_data. Pro náhradu stačí, že se dá zapsat v hranatých
    # závorkách.
    def __class_getitem__(cls, _polozka):
        return cls

class ConfigSubentry: pass
class _Flow:
    def __init_subclass__(cls, **kw): pass
class ConfigFlow(_Flow): pass
class OptionsFlow(_Flow): pass
class ConfigSubentryFlow(_Flow): pass
SubentryFlowResult = dict
