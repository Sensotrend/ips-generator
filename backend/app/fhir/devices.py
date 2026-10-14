"""Medical Devices section (optional, LOINC 46264-8) -> DeviceUseStatement + Device.

One ``DeviceUseStatement`` (status ``active``: the document lists the device under what the
patient uses) per ``DeviceItem``, pointing at a ``Device`` whose ``type`` is the text as written
plus any lookup coding for ``device_text`` and whose ``deviceName`` is the brand or model. The
Device id is derived from the item id (stable across re-assemblies). The IPS profile requires
``timing[x]``, which the documents do not give: it carries a ``data-absent-reason`` of
``unknown``. Only the statement is a section entry and has a narrative line. The section is
emitted only when there is an item.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    SectionResult,
    concept,
    data_absent,
    entries_section,
    reference,
    urn_uuid,
)
from app.fhir.constants import PROFILE_DEVICE, PROFILE_DEVICE_USE_STATEMENT, SECTION_MEDICAL_DEVICES
from app.fhir.models import (
    Annotation,
    CodeableConcept,
    Device,
    DeviceName,
    DeviceUseStatement,
    Meta,
)
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import DeviceItem, Enriched

KEY = "devices"
TITLE = "Medical Devices"


def map_devices(items: list[Enriched[DeviceItem]], ctx: MappingContext) -> SectionResult | None:
    if not items:
        return None
    statements: list[MappedResource] = []
    entries: list[MappedResource] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        statement, device = map_device(item, path=f"{KEY}[{index}]", ctx=ctx)
        statements.append(statement)
        entries += [statement, device]
    section = entries_section(SECTION_MEDICAL_DEVICES, TITLE, statements)
    return SectionResult(section, KEY, entries, notes)


def map_device(
    item: Enriched[DeviceItem], *, path: str, ctx: MappingContext
) -> tuple[MappedResource, MappedResource]:
    d = item.extracted
    device_id = uuid5(NAMESPACE_URL, f"urn:uuid:{item.id}#device")
    device_url = urn_uuid(device_id)
    details: list[tuple[str, str]] = [("status", "in use")]
    if d.brand_text:
        details.insert(0, ("brand", d.brand_text))
    if d.note:
        details.append(("note", d.note))
    line = NarrativeLine(d.device_text, tuple(details))
    device = Device(
        id=str(device_id),
        meta=Meta(profile=[PROFILE_DEVICE]),
        text=line_narrative(NarrativeLine(d.brand_text or d.device_text)),
        type=concept(d.device_text, item.codings_for("device_text"))
        or CodeableConcept(text=d.device_text),
        device_name=(
            [DeviceName(name=d.brand_text, type="user-friendly-name")] if d.brand_text else None
        ),
    )
    statement = DeviceUseStatement(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_DEVICE_USE_STATEMENT]),
        text=line_narrative(line),
        status="active",
        subject=ctx.patient,
        primitive_extensions={"timingDateTime": data_absent()},
        device=reference(device_url),
        note=[Annotation(text=d.note)] if d.note else None,
    )
    return (
        MappedResource(path, item.id, urn_uuid(item.id), statement, line),
        MappedResource(path, item.id, device_url, device, None),
    )
