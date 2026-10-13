"""The pipeline as a ``Device``: ``Composition.author`` of every generated summary (D-4).

IPS distinguishes "automatically generated" from "human-curated" summaries by author type, so
the author is the software, never the reviewer (who becomes a ``Composition.attester`` on
approval in Phase 3). No IPS profile applies: ``Device-uv-ips`` describes devices used by the
patient and ``Device-observer-uv-ips`` observation devices; the Bundle's ``device`` slice has
no profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from app import __version__
from app.fhir.common import MappedResource, urn_uuid
from app.fhir.models import CodeableConcept, Device, DeviceName, DeviceVersion
from app.fhir.narrative import NarrativeLine, line_narrative


@dataclass(frozen=True, slots=True)
class PipelineInfo:
    name: str = "IPS Generator extraction pipeline"
    version: str = __version__

    @property
    def device_id(self) -> UUID:
        """Same id for the same pipeline name and version, across documents."""
        return uuid5(NAMESPACE_URL, f"ips-generator:device:{self.name}:{self.version}")


def map_pipeline_device(pipeline: PipelineInfo, *, schema_version: str) -> MappedResource:
    device_id = pipeline.device_id
    resource = Device(
        id=str(device_id),
        text=line_narrative(
            NarrativeLine(
                pipeline.name,
                (("version", pipeline.version), ("intermediate schema", schema_version)),
            )
        ),
        status="active",
        device_name=[DeviceName(name=pipeline.name, type="model-name")],
        version=[
            DeviceVersion(type=CodeableConcept(text="software"), value=pipeline.version),
            DeviceVersion(type=CodeableConcept(text="intermediate schema"), value=schema_version),
        ],
    )
    return MappedResource("", None, urn_uuid(device_id), resource)
