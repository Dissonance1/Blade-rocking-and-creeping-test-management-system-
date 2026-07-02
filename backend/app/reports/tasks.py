"""
Celery tasks for asynchronous report generation.

The task updates the ``Report`` model's status field at each stage so
the frontend can poll for completion.  On failure, the error message is
persisted to the database.

Task flow
---------
1. Set report status → ``GENERATING``
2. Call the appropriate :class:`~app.reports.generator.ReportGenerator` method
3. Write the output file to ``REPORTS_DIR``
4. Set report status → ``READY`` with ``file_path``

On any unhandled exception: set status → ``FAILED`` with ``error_message``.
"""

from __future__ import annotations

import asyncio
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Celery app — imported lazily to allow the module to be imported in
# environments where Celery is not configured (e.g. unit tests).
# ---------------------------------------------------------------------------

def _get_celery_app():  # noqa: ANN201
    from app.worker import celery_app
    return celery_app


# ---------------------------------------------------------------------------
# Report type → generator method mapping
# ---------------------------------------------------------------------------

REPORT_TYPE_EXCEL = "excel"
REPORT_TYPE_PDF = "pdf"
VALID_REPORT_TYPES = (REPORT_TYPE_EXCEL, REPORT_TYPE_PDF)


# ---------------------------------------------------------------------------
# Async core — decoupled from Celery so it can be tested independently
# ---------------------------------------------------------------------------

async def _run_report_generation(
    report_id: UUID,
    report_type: str,
    filter_params: dict,
) -> None:
    """
    Core async logic for report generation.

    Fetches the Report record, generates the file, and updates the record.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.database import async_session_factory  # type: ignore[import]
    from app.models.report import Report, ReportStatus  # type: ignore[import]
    from app.reports.generator import ReportGenerator

    async with async_session_factory() as db:
        db: AsyncSession

        # Fetch report record
        from sqlalchemy import select

        result = await db.execute(select(Report).where(Report.id == report_id))
        report: Report | None = result.scalar_one_or_none()

        if report is None:
            logger.error("report_task_report_not_found", report_id=str(report_id))
            return

        # Mark as generating
        report.status = ReportStatus.GENERATING
        report.started_at = datetime.now(tz=timezone.utc)
        await db.commit()

        logger.info(
            "report_generation_started",
            report_id=str(report_id),
            report_type=report_type,
        )

        try:
            # Resolve blade IDs from filter parameters
            blade_ids: list[UUID] = _resolve_blade_ids(filter_params)

            generator = ReportGenerator()

            if report_type == REPORT_TYPE_EXCEL:
                file_bytes = await generator.generate_blade_report_excel(blade_ids, db)
                extension = "xlsx"
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif report_type == REPORT_TYPE_PDF:
                file_bytes = await generator.generate_blade_report_pdf(blade_ids, db)
                extension = "pdf"
                content_type = "application/pdf"
            else:
                raise ValueError(
                    f"Unknown report type '{report_type}'. "
                    f"Valid types: {VALID_REPORT_TYPES}"
                )

            # Write file to disk
            file_path = _save_report_file(
                report_id=report_id,
                file_bytes=file_bytes,
                extension=extension,
            )

            # Update report record to READY
            report.status = ReportStatus.READY
            report.file_path = str(file_path)
            report.file_size_bytes = len(file_bytes)
            report.content_type = content_type
            report.completed_at = datetime.now(tz=timezone.utc)
            report.error_message = None
            await db.commit()

            logger.info(
                "report_generation_completed",
                report_id=str(report_id),
                file_path=str(file_path),
                size_bytes=len(file_bytes),
            )

        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc()
            logger.error(
                "report_generation_failed",
                report_id=str(report_id),
                error=error_msg,
                traceback=tb,
            )

            try:
                await db.rollback()
                report.status = ReportStatus.FAILED
                report.error_message = error_msg
                report.completed_at = datetime.now(tz=timezone.utc)
                await db.commit()
            except Exception as db_exc:  # noqa: BLE001
                logger.error(
                    "report_status_update_failed",
                    report_id=str(report_id),
                    db_error=str(db_exc),
                )
            raise  # re-raise so Celery marks the task as FAILURE


def _resolve_blade_ids(filter_params: dict) -> list[UUID]:
    """
    Extract a list of :class:`uuid.UUID` blade IDs from *filter_params*.

    Supports three forms:

    * ``{"blade_ids": ["<uuid>", ...]}`` — explicit list
    * ``{"blade_id": "<uuid>"}`` — single blade shorthand
    * ``{}`` — empty (caller will receive an empty list; generator should
      handle this by returning all blades or an empty report)
    """
    blade_ids_raw = filter_params.get("blade_ids") or []
    if not blade_ids_raw and "blade_id" in filter_params:
        blade_ids_raw = [filter_params["blade_id"]]

    result: list[UUID] = []
    for raw in blade_ids_raw:
        try:
            result.append(UUID(str(raw)))
        except (ValueError, AttributeError) as exc:
            logger.warning("invalid_blade_id_skipped", raw=raw, error=str(exc))

    return result


def _save_report_file(
    report_id: UUID,
    file_bytes: bytes,
    extension: str,
) -> Path:
    """
    Write *file_bytes* to the configured reports directory and return the path.
    """
    reports_dir_str: str = os.environ.get("REPORTS_DIR", "reports")
    reports_dir = Path(reports_dir_str)
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"report_{report_id}_{timestamp}.{extension}"
    file_path = reports_dir / filename

    file_path.write_bytes(file_bytes)
    logger.debug("report_file_saved", path=str(file_path), size_bytes=len(file_bytes))
    return file_path


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------

def _register_tasks() -> None:
    """
    Register Celery tasks.  Called lazily so that the task functions are
    only bound to a Celery app when explicitly required.
    """
    celery_app = _get_celery_app()

    @celery_app.task(
        name="reports.generate_report_task",
        bind=True,
        max_retries=2,
        default_retry_delay=30,
        acks_late=True,
        track_started=True,
    )
    def generate_report_task(
        self,  # noqa: ANN001
        report_id: str,
        report_type: str,
        filter_params: dict,
    ) -> dict:
        """
        Celery task: generate a blade report asynchronously.

        Parameters
        ----------
        report_id:
            String UUID of the Report record to update.
        report_type:
            One of ``"excel"`` or ``"pdf"``.
        filter_params:
            Dictionary that may contain ``blade_ids`` (list of UUID strings)
            and/or other filter criteria.

        Returns
        -------
        dict
            ``{"status": "ok", "report_id": "<uuid>"}`` on success.
        """
        logger.info(
            "report_task_received",
            task_id=self.request.id,
            report_id=report_id,
            report_type=report_type,
        )

        try:
            asyncio.run(
                _run_report_generation(
                    report_id=UUID(report_id),
                    report_type=report_type,
                    filter_params=filter_params,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "report_task_failed",
                task_id=self.request.id,
                report_id=report_id,
                error=str(exc),
            )
            raise self.retry(exc=exc)

        return {"status": "ok", "report_id": report_id}


# Auto-register tasks when the module is imported within a Celery worker.
try:
    _register_tasks()
except Exception:  # noqa: BLE001
    # Not running inside a Celery worker context — that's fine.
    pass
