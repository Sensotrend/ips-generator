"""Tools Claude uses in the terminology loop (PLAN.md §2 step 5), plus the final-answer schema.

All tools are ``strict: true`` with ``additionalProperties: false``; requests use
``tool_choice: auto`` (forced tool choice returns 400 on Sonnet/Opus 5.5). Every tool takes the
``field_id`` it works on, so the loop can enforce per-field budgets.

The definitions are a fixed, ordered list: they are part of the cached prompt prefix (tools ->
system -> messages), so nothing request-specific may appear in them.

Claude never sees URIs: systems are short names (`CodeSystemName`). Search scopes are a closed
enum per tool, so Claude cannot point a search at an arbitrary value set.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.terminology.scopes import CodeSystemName, SearchScope


class ToolName(StrEnum):
    SEARCH_SNOMED = "search_snomed"
    SEARCH_LOINC = "search_loinc"
    SEARCH_MEDICATION = "search_medication"
    LOOKUP_CODE = "lookup_code"


SNOMED_TOOL_SCOPES: Final = (
    SearchScope.PROBLEM,
    SearchScope.ALLERGY_SUBSTANCE,
    SearchScope.CLINICAL_FINDING,
    SearchScope.BODY_STRUCTURE,
    SearchScope.SEVERITY,
    SearchScope.ROUTE,
)


class MedicationTerminology(StrEnum):
    """``search_medication`` targets."""

    SNOMED_PRODUCT = "snomed_product"
    ATC = "atc"
    DOSE_FORM = "dose_form"

    @property
    def scope(self) -> SearchScope:
        return {
            MedicationTerminology.SNOMED_PRODUCT: SearchScope.MEDICINAL_PRODUCT,
            MedicationTerminology.ATC: SearchScope.ATC,
            MedicationTerminology.DOSE_FORM: SearchScope.DOSE_FORM,
        }[self]


LOOKUP_SYSTEMS: Final = (CodeSystemName.ICD_10, CodeSystemName.ATC, CodeSystemName.SNOMED_CT)


# --------------------------------------------------------------------------------------------
# Tool inputs (validated again in Python after the strict grammar)
# --------------------------------------------------------------------------------------------

_INPUT = ConfigDict(extra="forbid", frozen=True)


class SearchSnomedInput(BaseModel):
    model_config = _INPUT
    field_id: str
    scope: SearchScope
    query: str


class SearchLoincInput(BaseModel):
    model_config = _INPUT
    field_id: str
    query: str


class SearchMedicationInput(BaseModel):
    model_config = _INPUT
    field_id: str
    terminology: MedicationTerminology
    query: str


class LookupCodeInput(BaseModel):
    model_config = _INPUT
    field_id: str
    system: Literal[CodeSystemName.ICD_10, CodeSystemName.ATC, CodeSystemName.SNOMED_CT]
    code: str


TOOL_INPUTS: Final[dict[ToolName, type[BaseModel]]] = {
    ToolName.SEARCH_SNOMED: SearchSnomedInput,
    ToolName.SEARCH_LOINC: SearchLoincInput,
    ToolName.SEARCH_MEDICATION: SearchMedicationInput,
    ToolName.LOOKUP_CODE: LookupCodeInput,
}


# --------------------------------------------------------------------------------------------
# Tool definitions
# --------------------------------------------------------------------------------------------

_FIELD_ID = {"type": "string", "description": 'The field you are coding, e.g. "f3".'}
_QUERY = {
    "type": "string",
    "description": "Short English clinical term (1-6 words), as a terminology would name it. "
    "Translate Finnish/Swedish terms and expand abbreviations; no dates, numbers or names.",
}


def _tool(name: ToolName, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name.value,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def tool_definitions() -> list[dict[str, Any]]:
    """The tool list sent with every terminology request (stable order and content)."""
    return [
        _tool(
            ToolName.SEARCH_SNOMED,
            "Search SNOMED CT (international, English) for a clinical term. Use it for "
            "conditions (scope problem), allergy substances (allergy_substance), reaction "
            "manifestations (clinical_finding), body sites (body_structure), condition severity "
            "(severity) and routes of administration (route). Returns up to 10 candidates "
            "(code + display); only codes returned by a tool may be chosen.",
            {
                "field_id": _FIELD_ID,
                "scope": {"type": "string", "enum": [s.value for s in SNOMED_TOOL_SCOPES]},
                "query": _QUERY,
            },
        ),
        _tool(
            ToolName.SEARCH_LOINC,
            "Search LOINC (English) for a laboratory test or observation name. Returns up to 10 "
            "candidates.",
            {"field_id": _FIELD_ID, "query": _QUERY},
        ),
        _tool(
            ToolName.SEARCH_MEDICATION,
            "Search medication terminologies: snomed_product = SNOMED CT medicinal products "
            '(e.g. "Metformin only product"), atc = WHO ATC (substance level, e.g. '
            '"metformin"), dose_form = EDQM pharmaceutical dose forms (e.g. "Film-coated '
            'tablet"). Search brand names by their active ingredient(s). Returns up to 10 '
            "candidates.",
            {
                "field_id": _FIELD_ID,
                "terminology": {"type": "string", "enum": [t.value for t in MedicationTerminology]},
                "query": _QUERY,
            },
        ),
        _tool(
            ToolName.LOOKUP_CODE,
            "Look up a code printed in the document (given in the field's printed_code) to see "
            "whether it exists and what it means. Only printed codes can be chosen this way.",
            {
                "field_id": _FIELD_ID,
                "system": {"type": "string", "enum": [s.value for s in LOOKUP_SYSTEMS]},
                "code": {"type": "string", "description": "The printed code, as given."},
            },
        ),
    ]


# --------------------------------------------------------------------------------------------
# Final answer (structured output)
# --------------------------------------------------------------------------------------------


class ChosenCode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_id: str
    system: CodeSystemName
    code: str


class CodingAnswer(BaseModel):
    """Claude's final answer: chosen codes; fields without a matching candidate are omitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codes: list[ChosenCode] = Field(default_factory=list)


def answer_output_format() -> dict[str, Any]:
    """``output_config.format`` for the final answer."""
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "description": "One entry per chosen code; at most one code per field and "
                    "code system. Omit fields with no candidate of the same meaning.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_id": {"type": "string"},
                            "system": {"type": "string", "enum": [s.value for s in CodeSystemName]},
                            "code": {"type": "string"},
                        },
                        "required": ["field_id", "system", "code"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["codes"],
            "additionalProperties": False,
        },
    }
