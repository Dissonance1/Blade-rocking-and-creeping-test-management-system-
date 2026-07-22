"""
Shared Python enums used across SQLAlchemy models and Pydantic schemas.

Keeping all enums in one module prevents circular imports and makes it
easy to introspect the full domain vocabulary in one place.
"""

import enum


class RoleName(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    OH_OPERATOR = "OH_OPERATOR"
    ASSEMBLY_OPERATOR = "ASSEMBLY_OPERATOR"
    QA_VIEWER = "QA_VIEWER"


class BladeStatus(str, enum.Enum):
    CREATED = "CREATED"
    OH_INSPECTION = "OH_INSPECTION"
    MEASUREMENTS_RECORDED = "MEASUREMENTS_RECORDED"
    SENT_TO_ASSEMBLY = "SENT_TO_ASSEMBLY"
    ASSEMBLY_RECEIVED = "ASSEMBLY_RECEIVED"   # batch marked received at 720 Hanger
    ASSEMBLY_VERIFIED = "ASSEMBLY_VERIFIED"   # blade scanned & accepted at Assembly
    SLOT_ASSIGNED = "SLOT_ASSIGNED"
    BALANCING_IN_PROGRESS = "BALANCING_IN_PROGRESS"
    BALANCING_COMPLETED = "BALANCING_COMPLETED"
    RETURNED_TO_OH = "RETURNED_TO_OH"
    FINAL_VERIFICATION = "FINAL_VERIFICATION"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"


class MeasurementType(str, enum.Enum):
    INITIAL = "INITIAL"
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class StationType(str, enum.Enum):
    OH = "OH"
    ASSEMBLY = "ASSEMBLY"
    QA = "QA"
    ADMIN = "ADMIN"


class NotificationType(str, enum.Enum):
    BLADE_RECEIVED = "BLADE_RECEIVED"
    SLOT_PENDING = "SLOT_PENDING"
    BALANCING_DONE = "BALANCING_DONE"
    BLADE_REJECTED = "BLADE_REJECTED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    SYSTEM = "SYSTEM"
    WORKFLOW_UPDATED = "WORKFLOW_UPDATED"
    GENERAL = "GENERAL"


class ReportType(str, enum.Enum):
    PDF = "PDF"
    EXCEL = "EXCEL"


class ReportStatus(str, enum.Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class AttachmentType(str, enum.Enum):
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    OCR_SCAN = "OCR_SCAN"


class BladeType(str, enum.Enum):
    LPTR = "LPTR"   # Low Pressure Turbine Rotor — Rocking + Creep tests
    HPTR = "HPTR"   # High Pressure Turbine Rotor — Rocking only (no Creep)


class LptrCorrectionType(str, enum.Enum):
    REARRANGEMENT = "REARRANGEMENT"
    BALANCING_ADJUSTMENT = "BALANCING_ADJUSTMENT"
    MANUFACTURER_REPLACEMENT_REQUEST = "MANUFACTURER_REPLACEMENT_REQUEST"


class BatchEventType(str, enum.Enum):
    CREATED = "CREATED"
    MEASUREMENTS_RECORDED = "MEASUREMENTS_RECORDED"
    SENT_TO_ASSEMBLY = "SENT_TO_ASSEMBLY"
    RECEIVED_BY_ASSEMBLY = "RECEIVED_BY_ASSEMBLY"
    ACCEPTED = "ACCEPTED"
    MODIFIED = "MODIFIED"
    SLOTS_ALLOCATED = "SLOTS_ALLOCATED"
    SET_MAKING = "SET_MAKING"
    BALANCED = "BALANCED"
    RETURNED_TO_OH = "RETURNED_TO_OH"     # Assembly reports LPTR balancing task complete, sends blades back
    ACCEPTED_BY_OH = "ACCEPTED_BY_OH"     # OH acknowledges + accepts the returned work order


class AssemblyVerificationStatus(str, enum.Enum):
    PENDING = "PENDING"       # blade arrived at Assembly, not yet scanned
    ACCEPTED = "ACCEPTED"     # readings match OH; accepted as-is
    MODIFIED = "MODIFIED"     # accepted with operator-overridden readings
    REJECTED = "REJECTED"     # rejected at Assembly (out of tolerance / damage)
