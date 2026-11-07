"""Contract for reviewed source adapters.

Planning must not authenticate or query a provider. Validation reads prepared
files, and only approved public metadata may enter delivery manifests.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True)
class SourceUnit:
    source_id: str
    profile_id: str
    anchor_id: str
    year: int
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class SourcePlan:
    unit: SourceUnit
    state: str
    reason: str
    work_key: str  # Includes profile version, native cell/context and period.
    remote_operations: int | None
    estimated_bytes: int | None


@dataclass(frozen=True)
class PreparedSource:
    unit: SourceUnit
    files: tuple[Path, ...]
    public_metadata: Mapping[str, object]


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    checks: Mapping[str, str]
    gaps: tuple[str, ...]


class SourceAdapter(Protocol):
    source_id: str
    profile_id: str

    def plan(self, unit: SourceUnit, *, asset_root: Path) -> SourcePlan:
        """Inspect local holdings and registered coverage without network calls."""
        ...

    def prepare(self, plan: SourcePlan, *, output_root: Path,
                credential_ref: Path | None) -> PreparedSource:
        """Execute an authorized bounded plan with checkpoint/retry limits."""
        ...

    def validate(self, prepared: PreparedSource) -> ValidationResult:
        """Read outputs and validate identity, grid, time, units and masks."""
        ...


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter):
        from .catalogue import SOURCE_COLUMNS
        if adapter.source_id not in SOURCE_COLUMNS or not adapter.profile_id:
            raise ValueError('Adapter requires a registered source and explicit profile version')
        if adapter.source_id in self._adapters:
            raise ValueError('An adapter is already registered for this source')
        self._adapters[adapter.source_id] = adapter

    def require(self, source_id: str) -> SourceAdapter:
        if source_id not in self._adapters:
            raise NotImplementedError(f'No reviewed preparation adapter registered for {source_id}')
        return self._adapters[source_id]


def default_registry():
    from .gldas21 import GLDAS21Adapter
    from .context_sources import ContextAdapter, PROFILES
    from .modis_sources import MODISAdapter, PROFILES as MODIS_PROFILES
    from .timeseries_sources import TimeSeriesAdapter, PROFILES as TIMESERIES_PROFILES
    from .sentinel1_sources import Sentinel1Adapter
    from .smap_sources import SMAPL4Adapter
    registry = AdapterRegistry()
    registry.register(GLDAS21Adapter())
    registry.register(Sentinel1Adapter())
    registry.register(SMAPL4Adapter())
    for source in PROFILES:
        registry.register(ContextAdapter(source))
    for source in MODIS_PROFILES:
        registry.register(MODISAdapter(source))
    for source in TIMESERIES_PROFILES:
        registry.register(TimeSeriesAdapter(source))
    return registry
