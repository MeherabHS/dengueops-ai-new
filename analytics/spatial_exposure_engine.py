"""Deprecated non-executable spatial formula stub.

The sole temporary prototype authority is
``operational_engine.compute_exposure_weights`` governed by formula IDs
OPS.EXPOSURE.COMPOSITION and OPS.EXPOSURE.ANOMALY. The former Phase 0 weights,
multiplicative anomaly rule, allocation, and priority expression were
contradictory and must not be used as alternatives.
"""

from __future__ import annotations


class DeprecatedSpatialFormulaError(RuntimeError):
    """Raised whenever the retired spatial stub is invoked."""


def _deprecated() -> None:
    raise DeprecatedSpatialFormulaError(
        "The Phase 0 spatial formula is deprecated and non-executable; use the "
        "governed operational-engine formula IDs instead."
    )


def compute_exposure_index(*_args, **_kwargs):
    _deprecated()


def allocate_cases(*_args, **_kwargs):
    _deprecated()


def compute_priority_score(*_args, **_kwargs):
    _deprecated()


if __name__ == "__main__":
    _deprecated()
