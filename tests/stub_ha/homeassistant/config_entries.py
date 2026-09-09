
class ConfigEntry: pass
class ConfigSubentry: pass
class _Flow:
    def __init_subclass__(cls, **kw): pass
class ConfigFlow(_Flow): pass
class OptionsFlow(_Flow): pass
class ConfigSubentryFlow(_Flow): pass
SubentryFlowResult = dict
