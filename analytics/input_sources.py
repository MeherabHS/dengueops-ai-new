"""Deterministic input-source selection for the DengueOps analytics pipeline."""

from __future__ import annotations

from dataclasses import dataclass


CASE_SOURCES = ("synthetic_demo", "opendengue", "synthetic_benchmark")
CLIMATE_SOURCES = ("synthetic_demo", "nasa_power", "synthetic_benchmark")
OPERATIONAL_SOURCES = ("synthetic_demo", "synthetic_benchmark")

RESERVED_SOURCES: set[str] = set()
SOURCE_CLASSES = ("synthetic", "public_real", "official")


@dataclass(frozen=True)
class SourceDescriptor:
    source_id: str
    source_class: str
    canonical_tag: str
    geography_level: str | None = None
    geography_id: str | None = None


SOURCE_DESCRIPTORS: dict[str, SourceDescriptor] = {
    "synthetic_demo": SourceDescriptor(
        "synthetic_demo", "synthetic", "synthetic_demo", "city", "BGD-DHAKA-SOUTH"
    ),
    "opendengue": SourceDescriptor(
        "opendengue", "public_real", "opendengue", "national", "BGD"
    ),
    "nasa_power": SourceDescriptor(
        "nasa_power", "public_real", "nasa_power", "point", "BGD-DHAKA-SOUTH"
    ),
    "synthetic_benchmark": SourceDescriptor(
        "synthetic_benchmark", "synthetic", "synthetic_benchmark", "city", "BGD-DHAKA-SOUTH"
    ),
}


def get_source_descriptor(source_id: str) -> SourceDescriptor | None:
    """Return compact validation metadata for a selected source."""
    return SOURCE_DESCRIPTORS.get(source_id)


def get_descriptor_by_tag(source_tag: str) -> SourceDescriptor | None:
    """Resolve a canonical row-level source tag when reusing existing files."""
    return next(
        (d for d in SOURCE_DESCRIPTORS.values() if d.canonical_tag == source_tag),
        None,
    )


class SourcePlanError(ValueError):
    """Raised when source options are conflicting, ambiguous, or unavailable."""


@dataclass(frozen=True)
class ProducerCommand:
    """One producer invocation and the input domains it exclusively owns."""

    producer_id: str
    script_name: str
    domains: tuple[str, ...]
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class InputSourcePlan:
    case_source: str
    climate_source: str
    operational_source: str
    producers: tuple[ProducerCommand, ...]
    demo_domains: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    reuse_existing: bool = False

    def producer_for_domain(self, domain: str) -> str | None:
        """Return the sole producer ID for a domain, or None when reusing files."""
        matches = [p.producer_id for p in self.producers if domain in p.domains]
        if len(matches) > 1:
            raise SourcePlanError(f"Multiple producers selected for domain '{domain}'.")
        return matches[0] if matches else None


def _apply_legacy_alias(
    explicit: str | None,
    legacy_enabled: bool,
    legacy_value: str,
    option_name: str,
    legacy_name: str,
) -> tuple[str | None, str | None]:
    if not legacy_enabled:
        return explicit, None
    if explicit is not None and explicit != legacy_value:
        raise SourcePlanError(
            f"{legacy_name} conflicts with {option_name} {explicit}."
        )
    return legacy_value, (
        f"{legacy_name} is deprecated; use {option_name} {legacy_value}."
    )


def resolve_input_plan(
    *,
    case_source: str | None = None,
    climate_source: str | None = None,
    operational_source: str | None = None,
    use_opendengue: bool = False,
    use_nasa_power_climate: bool = False,
    skip_data_generation: bool = False,
    benchmark_args: tuple[str, ...] = (),
) -> InputSourcePlan:
    """Resolve all producer ownership before any input file can be written."""
    explicit_selection = any(
        value is not None
        for value in (case_source, climate_source, operational_source)
    )
    legacy_selection = use_opendengue or use_nasa_power_climate

    if skip_data_generation:
        if explicit_selection or legacy_selection or benchmark_args:
            raise SourcePlanError(
                "--skip-data-generation cannot be combined with source selections "
                "or legacy source flags."
            )
        return InputSourcePlan(
            case_source="existing",
            climate_source="existing",
            operational_source="existing",
            producers=(),
            demo_domains=(),
            reuse_existing=True,
        )

    warnings: list[str] = []
    case_source, warning = _apply_legacy_alias(
        case_source,
        use_opendengue,
        "opendengue",
        "--case-source",
        "--use-opendengue",
    )
    if warning:
        warnings.append(warning)

    climate_source, warning = _apply_legacy_alias(
        climate_source,
        use_nasa_power_climate,
        "nasa_power",
        "--climate-source",
        "--use-nasa-power-climate",
    )
    if warning:
        warnings.append(warning)

    case_source = case_source or "synthetic_demo"
    climate_source = climate_source or "synthetic_demo"
    operational_source = operational_source or "synthetic_demo"

    if case_source not in CASE_SOURCES:
        raise SourcePlanError(f"Unknown case source '{case_source}'.")
    if climate_source not in CLIMATE_SOURCES:
        raise SourcePlanError(f"Unknown climate source '{climate_source}'.")
    if operational_source not in OPERATIONAL_SOURCES:
        raise SourcePlanError(f"Unknown operational source '{operational_source}'.")

    selected = (case_source, climate_source, operational_source)
    benchmark_count = sum(source == "synthetic_benchmark" for source in selected)
    if benchmark_count not in (0, 3):
        raise SourcePlanError(
            "synthetic_benchmark is recognized but not implemented as a partial selection; "
            "it requires case, climate, and operational sources together."
        )
    if benchmark_args and benchmark_count != 3:
        raise SourcePlanError("Benchmark options require all three synthetic_benchmark sources.")
    if benchmark_count and legacy_selection:
        raise SourcePlanError("Legacy source flags cannot be combined with synthetic_benchmark.")

    for source in (case_source, climate_source, operational_source):
        if source in RESERVED_SOURCES:
            raise SourcePlanError(
                f"Source '{source}' is recognized but not implemented."
            )

    demo_domains = tuple(
        domain
        for domain, source in (
            ("cases", case_source),
            ("climate", climate_source),
            ("operational", operational_source),
        )
        if source == "synthetic_demo"
    )

    producers: list[ProducerCommand] = []
    if demo_domains:
        producers.append(
            ProducerCommand(
                producer_id="generate_demo_data",
                script_name="generate_demo_data.py",
                domains=demo_domains,
                args=("--domains", *demo_domains),
            )
        )
    if case_source == "opendengue":
        producers.append(
            ProducerCommand(
                producer_id="fetch_opendengue",
                script_name="fetch_opendengue.py",
                domains=("cases",),
            )
        )
    if climate_source == "nasa_power":
        producers.append(
            ProducerCommand(
                producer_id="fetch_nasa_power_climate",
                script_name="fetch_nasa_power_climate.py",
                domains=("climate",),
            )
        )
    if benchmark_count == 3:
        producers.append(
            ProducerCommand(
                producer_id="generate_benchmark_data",
                script_name="benchmark/generate_benchmark_data.py",
                domains=("cases", "climate", "operational"),
                args=benchmark_args,
            )
        )

    plan = InputSourcePlan(
        case_source=case_source,
        climate_source=climate_source,
        operational_source=operational_source,
        producers=tuple(producers),
        demo_domains=demo_domains,
        warnings=tuple(warnings),
    )

    for domain in ("cases", "climate", "operational"):
        if plan.producer_for_domain(domain) is None:
            raise SourcePlanError(f"No producer selected for domain '{domain}'.")

    return plan
