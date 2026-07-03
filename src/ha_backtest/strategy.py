from __future__ import annotations

from .core.target_weights import make_target_weight_strategy


def make_ha_premium_strategy(*args, **kwargs):
    return make_target_weight_strategy(*args, **kwargs)
