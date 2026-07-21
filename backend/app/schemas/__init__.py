"""
Pydantic v2 schema package for Blade Rocking & Creep Test Management System.

All public schema classes are re-exported here for convenience so that
routers and services can import from ``app.schemas`` directly:

    from app.schemas import BladeResponse, BladeCreate, PaginatedResponse
"""

# Base primitives
from app.schemas.base import (
    BaseSchema,
    ErrorDetail,
    ErrorResponse,
    PaginatedResponse,
    StatusResponse,
)

# User / auth
from app.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    PermissionResponse,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    RoleResponse,
    Token,
    TokenData,
    UserCreate,
    UserListItem,
    UserResponse,
    UserUpdate,
)

# Blade
from app.schemas.blade import (
    BladeListItem,
    BladeResponse,
    BladeSearchParams,
    BladeUpdate,
    SendToAssemblyRequest,
    StationSummary,
)

# Work order
from app.schemas.work_order import (
    WorkOrderCompleteResponse,
    WorkOrderCreate,
    WorkOrderDetailResponse,
    WorkOrderRowResponse,
    WorkOrderRowUpdate,
)

# Measurement
from app.schemas.measurement import (
    MeasurementCreate,
    MeasurementResponse,
    MeasurementUpdate,
)

# Slot allocation
from app.schemas.slot_allocation import (
    BalancingUpdateRequest,
    SlotAllocationResponse,
    SlotAssignRequest,
    SlotReassignRequest,
)

# Workflow
from app.schemas.workflow import (
    BladeSummaryForHistory,
    StationResponse,
    WorkflowHistoryResponse,
    WorkflowLogResponse,
)

# Notification
from app.schemas.notification import (
    NotificationBatchReadRequest,
    NotificationResponse,
    NotificationUpdate,
)

# Report
from app.schemas.report import (
    ReportFilterParams,
    ReportGenerateRequest,
    ReportResponse,
)

__all__ = [
    # base
    "BaseSchema",
    "ErrorDetail",
    "ErrorResponse",
    "PaginatedResponse",
    "StatusResponse",
    # user / auth
    "ChangePasswordRequest",
    "LoginRequest",
    "PermissionResponse",
    "ProfileUpdateRequest",
    "RefreshTokenRequest",
    "RoleResponse",
    "Token",
    "TokenData",
    "UserCreate",
    "UserListItem",
    "UserResponse",
    "UserUpdate",
    # blade
    "BladeListItem",
    "BladeResponse",
    "BladeSearchParams",
    "BladeUpdate",
    "SendToAssemblyRequest",
    "StationSummary",
    # work order
    "WorkOrderCompleteResponse",
    "WorkOrderCreate",
    "WorkOrderDetailResponse",
    "WorkOrderRowResponse",
    "WorkOrderRowUpdate",
    # measurement
    "MeasurementCreate",
    "MeasurementResponse",
    "MeasurementUpdate",
    # slot allocation
    "BalancingUpdateRequest",
    "SlotAllocationResponse",
    "SlotAssignRequest",
    "SlotReassignRequest",
    # workflow
    "BladeSummaryForHistory",
    "StationResponse",
    "WorkflowHistoryResponse",
    "WorkflowLogResponse",
    # notification
    "NotificationBatchReadRequest",
    "NotificationResponse",
    "NotificationUpdate",
    # report
    "ReportFilterParams",
    "ReportGenerateRequest",
    "ReportResponse",
]
