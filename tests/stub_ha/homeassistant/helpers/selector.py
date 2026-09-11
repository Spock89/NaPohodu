
class _S:
    def __init__(self, *a, **k): pass
    def __call__(self, v=None): return v
EntitySelector=_S; EntitySelectorConfig=_S; NumberSelector=_S
NumberSelectorConfig=_S; TextSelector=_S; TextSelectorConfig=_S
SelectSelector=_S; SelectSelectorConfig=_S; TimeSelector=_S
BooleanSelector=_S; BooleanSelectorConfig=_S
class NumberSelectorMode: BOX="box"; SLIDER="slider"
class SelectSelectorMode: DROPDOWN="dropdown"; LIST="list"
