"""Synthetic ``EnrichedIps`` variants for the assembly tests (unit and Matchbox integration).

All built from the synthetic fixture ``enriched_discharge_summary_fi.json`` (no real data).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.pipeline.derive import apply_derivations
from app.schemas.intermediate import EnrichedIps

FIXTURE = Path(__file__).parent / "fixtures" / "intermediate" / "enriched_discharge_summary_fi.json"
NOW = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.UTC)

SECTIONS = ("allergies", "medications", "problems")
SECTION_KINDS = ("items_found", "none_known", "no_information")


def base_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def statement(quote: str, **extra: Any) -> dict[str, Any]:
    return {"source_quote": quote, "page": 1, "locator": "line 6", "confidence": "high", **extra}


def none_known(section: str) -> dict[str, Any]:
    if section == "allergies":
        return {"kind": "none_known", **statement("Ei tiedossa olevia allergioita", scope="all")}
    return {"kind": "none_known", **statement("Ei säännöllistä lääkitystä")}


def condition(
    item_id: int, text: str, status: str, *, abatement: str | None = None
) -> dict[str, Any]:
    return {
        "id": f"0b0c5f3e-6c1a-4b7e-9a51-0000000001{item_id:02d}",
        "extracted": {
            "source_quote": text,
            "page": 1,
            "locator": "line 12",
            "condition_text": text,
            "printed_code": None,
            "printed_code_system_text": None,
            "clinical_status": status,
            "verification_status": "not_stated",
            "severity": "not_stated",
            "body_site_text": None,
            "onset": None,
            "abatement": abatement,
            "note": None,
            "confidence": "high",
        },
        "codings": [],
    }


def build(mutate: Callable[[dict[str, Any]], None] | None = None) -> EnrichedIps:
    data = base_data()
    if mutate is not None:
        mutate(data)
    return EnrichedIps.model_validate(data)


def with_section(section: str, kind: str) -> EnrichedIps:
    def mutate(data: dict[str, Any]) -> None:
        if kind == "none_known":
            data[section] = none_known(section)
        elif kind == "no_information":
            data[section] = {"kind": "no_information"}

    return build(mutate)


def nkda_and_items() -> EnrichedIps:
    """Food allergy + NKDA (coded) + NK environmental (coded) + NK food (conflict) + NK all."""

    def mutate(data: dict[str, Any]) -> None:
        data["allergies"]["none_known_statements"] = [
            statement("Ei tiedossa olevia lääkeaineallergioita", scope="medication"),
            statement("Ei ympäristöallergioita", scope="environment"),
            statement("Ei ruoka-allergioita", scope="food"),
            statement("Ei allergioita", scope="all"),
            statement("NKDA", scope="medication"),
        ]

    return build(mutate)


def past_illness() -> EnrichedIps:
    def mutate(data: dict[str, Any]) -> None:
        data["problems"]["items"] += [
            condition(1, "Umpilisäketulehdus", "resolved", abatement="2010-05"),
            condition(2, "Masennus", "remission"),
            condition(3, "Astma lapsena", "inactive"),
            condition(4, "Keuhkokuume", "not_stated", abatement="2019"),
            condition(5, "Migreeni", "active", abatement="2020"),
        ]

    return build(mutate)


def only_past() -> EnrichedIps:
    def mutate(data: dict[str, Any]) -> None:
        data["problems"]["items"] = [condition(1, "Umpilisäketulehdus", "resolved")]

    return build(mutate)


def with_birth_date() -> EnrichedIps:
    def mutate(data: dict[str, Any]) -> None:
        data["patient"]["birth_date"] = {**statement("s. 15.3.1972"), "value": "1972-03-15"}

    return build(mutate)


def without_name() -> EnrichedIps:
    def mutate(data: dict[str, Any]) -> None:
        data["patient"]["names"] = []

    return build(mutate)


NEVER_ISSUED_HETU = "010140+123R"
"""Born 1840-01-01, individual number 123 (odd = male). Structurally valid, but nobody born in
1840 was alive (aged 124+) when Finnish identity codes were introduced in 1964, so it was never
issued (no real data). Used where a 002-899 number is needed (no sex is derived from 900-999)."""


def derived_birth_date() -> EnrichedIps:
    """D-10: no stated birth date; derived from the fixture's synthetic HETU (900-999: no sex)."""
    enriched, _ = apply_derivations(build())
    return enriched


def derived_birth_date_and_gender() -> EnrichedIps:
    """D-10: neither birth date nor gender stated; both derived (individual number 123)."""

    def mutate(data: dict[str, Any]) -> None:
        data["patient"]["gender"] = None
        identifier = data["patient"]["identifiers"][0]
        identifier["value"] = NEVER_ISSUED_HETU
        identifier["source_quote"] = f"Henkilötunnus: {NEVER_ISSUED_HETU}"

    enriched, _ = apply_derivations(build(mutate))
    return enriched


def all_variants() -> dict[str, EnrichedIps]:
    """Every case that must validate against IPS 2.0.1 with 0 errors and no unmatched entry."""
    cases = {
        "fixture_missing_birth_date": build(),
        "with_birth_date": with_birth_date(),
        "derived_birth_date": derived_birth_date(),
        "derived_birth_date_and_gender": derived_birth_date_and_gender(),
        "without_name": without_name(),
        "nkda_and_items": nkda_and_items(),
        "past_illness": past_illness(),
        "only_past": only_past(),
    }
    for section in SECTIONS:
        for kind in ("none_known", "no_information"):
            cases[f"{section}_{kind}"] = with_section(section, kind)
    cases["all_no_information"] = build(
        lambda d: d.update({s: {"kind": "no_information"} for s in SECTIONS})
    )
    cases["all_none_known"] = build(lambda d: d.update({s: none_known(s) for s in SECTIONS}))
    return {name: copy.deepcopy(case) for name, case in cases.items()}
