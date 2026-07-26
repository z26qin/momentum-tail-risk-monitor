"""Legacy domain checklist; active experimental conditions live in src.experiments."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.monitoring.contracts import (
    SCHEMA_VERSION,
    ArtifactProvenance,
    DomainRiskComponent,
    DomainRiskState,
    RiskState,
    StructuredMarketContext,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    read_json,
    sha256_file,
    write_json,
)


PRIOR_MARKET_DECLINE_THRESHOLD = -0.10
HIGH_VOLATILITY_PERCENTILE_THRESHOLD = 0.80
MARKET_REBOUND_5D_THRESHOLD = 0.03
LOSER_SNAPBACK_5D_THRESHOLD = 0.03
MOMENTUM_DRAWDOWN_THRESHOLD = -0.20
BETA_CHANGE_ABSOLUTE_THRESHOLD = 0.10
POSITIONING_PROXY_PERCENTILE_THRESHOLD = 0.90


@dataclass(frozen=True)
class _ComponentSpec:
    component: str
    category: str
    context_field: str
    threshold: float
    comparison: str
    unit: str
    rationale: str


COMPONENT_SPECS = (
    _ComponentSpec(
        component="severe_prior_market_decline",
        category="precondition",
        context_field="market_return_504d",
        threshold=PRIOR_MARKET_DECLINE_THRESHOLD,
        comparison="less_than_or_equal",
        unit="decimal_return",
        rationale=(
            "A material two-year market decline is the transparent panic-state "
            "precondition; a marginally negative return is not enough."
        ),
    ),
    _ComponentSpec(
        component="high_market_volatility",
        category="precondition",
        context_field="market_volatility_percentile_126d",
        threshold=HIGH_VOLATILITY_PERCENTILE_THRESHOLD,
        comparison="greater_than_or_equal",
        unit="expanding_percentile",
        rationale=(
            "High point-in-time market volatility is the second panic-state "
            "precondition."
        ),
    ),
    _ComponentSpec(
        component="sharp_market_rebound",
        category="trigger",
        context_field="market_return_5d",
        threshold=MARKET_REBOUND_5D_THRESHOLD,
        comparison="greater_than_or_equal",
        unit="decimal_return",
        rationale=(
            "A sharp short-window market rebound is the principal reversal "
            "trigger after a stressed market state."
        ),
    ),
    _ComponentSpec(
        component="loser_snapback",
        category="trigger",
        context_field="loser_minus_winner_return_5d",
        threshold=LOSER_SNAPBACK_5D_THRESHOLD,
        comparison="greater_than_or_equal",
        unit="decimal_return_spread",
        rationale=(
            "Past losers outperforming past winners is the portfolio-leg "
            "signature most directly associated with a momentum reversal."
        ),
    ),
    _ComponentSpec(
        component="momentum_drawdown_confirmation",
        category="confirmation",
        context_field="momentum_drawdown_252d",
        threshold=MOMENTUM_DRAWDOWN_THRESHOLD,
        comparison="less_than_or_equal",
        unit="decimal_drawdown",
        rationale=(
            "A deep momentum drawdown confirms that the factor is already "
            "under material pressure; it does not initiate the state alone."
        ),
    ),
    _ComponentSpec(
        component="exposure_instability_confirmation",
        category="confirmation",
        context_field="beta_change_21d",
        threshold=BETA_CHANGE_ABSOLUTE_THRESHOLD,
        comparison="absolute_greater_than_or_equal",
        unit="beta_change",
        rationale=(
            "A large change in momentum market beta flags unstable exposure, "
            "but remains a confirmation rather than a core trigger."
        ),
    ),
    _ComponentSpec(
        component="stretched_momentum_structure_proxy",
        category="proxy",
        context_field="positioning_proxy_percentile",
        threshold=POSITIONING_PROXY_PERCENTILE_THRESHOLD,
        comparison="greater_than_or_equal",
        unit="expanding_percentile",
        rationale=(
            "Extreme momentum-decile return dispersion is a stretching proxy, "
            "not observed positioning or leverage."
        ),
    ),
)


COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "less_than_or_equal": lambda value, threshold: value <= threshold,
    "greater_than_or_equal": lambda value, threshold: value >= threshold,
    "absolute_greater_than_or_equal": (
        lambda value, threshold: abs(value) >= threshold
    ),
}


def _provenance(role: str, path: Path) -> ArtifactProvenance:
    try:
        displayed_path = str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        displayed_path = str(path.resolve())
    return ArtifactProvenance(
        role=role,
        path=displayed_path,
        sha256=sha256_file(path),
    )


def _previous_values(
    context: StructuredMarketContext,
) -> dict[str, float | None]:
    return {
        change.metric: change.previous_value for change in context.changes
    }


def _is_triggered(
    value: float | None,
    *,
    threshold: float,
    comparison: str,
) -> bool:
    if value is None:
        return False
    return COMPARATORS[comparison](value, threshold)


def build_domain_components(
    context: StructuredMarketContext,
) -> tuple[DomainRiskComponent, ...]:
    """Evaluate every published threshold against current and prior facts."""

    prior = _previous_values(context)
    components: list[DomainRiskComponent] = []
    for spec in COMPONENT_SPECS:
        value = getattr(context, spec.context_field)
        previous_value = prior.get(spec.context_field)
        components.append(
            DomainRiskComponent(
                component=spec.component,
                category=spec.category,
                value=value,
                threshold=spec.threshold,
                comparison=spec.comparison,
                unit=spec.unit,
                available=value is not None,
                triggered=_is_triggered(
                    value,
                    threshold=spec.threshold,
                    comparison=spec.comparison,
                ),
                previous_triggered=(
                    None
                    if previous_value is None
                    else _is_triggered(
                        previous_value,
                        threshold=spec.threshold,
                        comparison=spec.comparison,
                    )
                ),
                rationale=spec.rationale,
            )
        )
    return tuple(components)


def _state(component_flags: dict[str, bool]) -> str:
    panic_precondition = (
        component_flags["severe_prior_market_decline"]
        and component_flags["high_market_volatility"]
    )
    reversal_triggers = sum(
        (
            component_flags["sharp_market_rebound"],
            component_flags["loser_snapback"],
        )
    )
    if panic_precondition and reversal_triggers == 2:
        return "active_reversal"
    if panic_precondition and reversal_triggers == 1:
        return "reversal_watch"
    if panic_precondition:
        return "stressed_precondition"
    return "normal"


def _previous_state(
    components: tuple[DomainRiskComponent, ...],
) -> str | None:
    if any(
        component.previous_triggered is None
        and component.category in {"precondition", "trigger"}
        for component in components
    ):
        return None
    return _state(
        {
            component.component: bool(component.previous_triggered)
            for component in components
        }
    )


def _mechanisms(
    components: tuple[DomainRiskComponent, ...],
) -> tuple[str, ...]:
    triggered = {
        component.component
        for component in components
        if component.triggered
    }
    selected: list[str] = []
    if triggered.intersection(
        {"severe_prior_market_decline", "high_market_volatility"}
    ):
        selected.append("generic risk-off or risk-on")
    if "sharp_market_rebound" in triggered:
        selected.append("rapid market rebound after stress")
    if "loser_snapback" in triggered:
        selected.append("loser squeeze")
    if "momentum_drawdown_confirmation" in triggered:
        selected.append("winner liquidation")
    if "exposure_instability_confirmation" in triggered:
        selected.append("factor rotation")
    if "stretched_momentum_structure_proxy" in triggered:
        selected.append("crowding or deleveraging")
    return tuple(selected)


def _interpretation(state: str) -> str:
    if state == "active_reversal":
        return (
            "The stressed-market preconditions and both reversal triggers are "
            "active: the market is rebounding and past losers are sharply "
            "outperforming past winners."
        )
    if state == "reversal_watch":
        return (
            "The market is in a stressed precondition and one of the two "
            "reversal triggers is active. Review loser behavior and rebound "
            "breadth before treating this as a full reversal."
        )
    if state == "stressed_precondition":
        return (
            "A severe prior market decline and high volatility create a "
            "fragile precondition, but neither the market-rebound nor "
            "loser-snapback trigger is active."
        )
    return (
        "The paired market-decline and high-volatility preconditions are not "
        "both present. Isolated confirmations do not create a reversal state."
    )


def build_domain_risk_state(
    *,
    context: StructuredMarketContext,
    legacy_risk_state: RiskState | None = None,
    provenance: tuple[ArtifactProvenance, ...] | None = None,
) -> DomainRiskState:
    """Build an interpretable state without fitting or reading outcomes."""

    if legacy_risk_state is not None and (
        legacy_risk_state.as_of_date != context.as_of_date
        or legacy_risk_state.as_of_timestamp != context.as_of_timestamp
    ):
        raise ValueError("Legacy benchmark does not match the context date")
    components = build_domain_components(context)
    flags = {
        component.component: component.triggered for component in components
    }
    state = _state(flags)
    previous_state = _previous_state(components)
    return DomainRiskState(
        schema_version=SCHEMA_VERSION,
        as_of_date=context.as_of_date,
        as_of_timestamp=context.as_of_timestamp,
        state=state,
        previous_state=previous_state,
        state_changed=(
            previous_state is not None and previous_state != state
        ),
        component_count=sum(component.triggered for component in components),
        max_components=len(components),
        components=components,
        mechanisms=_mechanisms(components),
        interpretation=_interpretation(state),
        legacy_benchmark_name=(
            None
            if legacy_risk_state is None
            else "B2 saved OOS probability (secondary benchmark)"
        ),
        legacy_benchmark_probability=(
            None
            if legacy_risk_state is None
            else legacy_risk_state.risk_probability
        ),
        legacy_benchmark_severity=(
            None
            if legacy_risk_state is None
            else legacy_risk_state.risk_severity
        ),
        legacy_benchmark_limitations=(
            ()
            if legacy_risk_state is None
            else legacy_risk_state.calibration_limitations
        ),
        limitations=(
            "Thresholds are transparent research heuristics, not fitted "
            "probability or trading thresholds.",
            "The state operationalizes selected Daniel-Moskowitz mechanisms "
            "with public factor and market proxies rather than security-level "
            "portfolio holdings.",
            "The dispersion component is not observed investor positioning.",
            "Same-day market values use the approved post-close assessment "
            "and next-session action convention.",
        ),
        data_quality_flags=(
            "domain_state_is_not_a_calibrated_probability",
            "core_state_requires_both_panic_preconditions",
            "confirmations_do_not_trigger_state_without_panic_preconditions",
            "legacy_b2_probability_is_secondary_only",
        ),
        provenance=provenance or context.provenance,
    )


def run_domain_risk_state(
    *,
    context_path: Path,
    legacy_risk_state_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[DomainRiskState, Path]:
    context = StructuredMarketContext.from_dict(read_json(context_path))
    legacy_state = (
        None
        if legacy_risk_state_path is None
        else RiskState.from_dict(read_json(legacy_risk_state_path))
    )
    provenance = [_provenance("structured_market_context", context_path)]
    if legacy_risk_state_path is not None:
        provenance.append(
            _provenance("legacy_b2_risk_state", legacy_risk_state_path)
        )
    state = build_domain_risk_state(
        context=context,
        legacy_risk_state=legacy_state,
        provenance=tuple(provenance),
    )
    path = (
        output_dir
        / "debug"
        / f"domain_risk_state_{state.as_of_date}.json"
    )
    write_json(path, state.to_dict())
    return state, path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--legacy-risk-state", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    state, path = run_domain_risk_state(
        context_path=args.context,
        legacy_risk_state_path=args.legacy_risk_state,
        output_dir=args.output_dir,
    )
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
