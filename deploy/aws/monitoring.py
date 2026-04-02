"""CloudWatch custom metrics publisher — IBR Defect Extraction System.

Author: Supreeth Mysore
Program: F135 | Classification: ITAR

ITAR NOTICE: This module publishes operational metrics for infrastructure that
processes technical data subject to ITAR 22 CFR Parts 120-130. Metric names and
dimensions must not leak classified part geometries or defect specifics. Only
aggregate counts and timing data are published.

Publishes to the 'IBRDefect' CloudWatch namespace:
  - PipelineExecutionTime: seconds per IBR run
  - DefectCount: total defects detected per run
  - MLAccuracy / MLPrecision / MLRecall: ML model performance
  - ErrorRate: pipeline failure percentage over a window
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

NAMESPACE = "IBRDefect"
PROGRAM_ID = "F135"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_cloudwatch_client = None


def _get_client():
    global _cloudwatch_client
    if _cloudwatch_client is None:
        _cloudwatch_client = boto3.client("cloudwatch", region_name=AWS_REGION)
    return _cloudwatch_client


def _base_dimensions(part_number: Optional[str] = None) -> list[dict]:
    dims = [
        {"Name": "Program", "Value": PROGRAM_ID},
        {"Name": "Environment", "Value": os.environ.get("APP_ENV", "production")},
    ]
    if part_number:
        dims.append({"Name": "PartNumber", "Value": part_number})
    return dims


def _put_metrics(metric_data: list[dict]) -> bool:
    try:
        client = _get_client()
        for i in range(0, len(metric_data), 20):
            batch = metric_data[i : i + 20]
            client.put_metric_data(Namespace=NAMESPACE, MetricData=batch)
        return True
    except ClientError:
        logger.exception("Failed to publish CloudWatch metrics")
        return False


def publish_pipeline_execution(
    part_number: str,
    execution_time_seconds: float,
    defect_count: int,
    disposition: str,
    phase_timings: Optional[dict[str, float]] = None,
) -> bool:
    """Publish metrics for a completed pipeline execution.

    Args:
        part_number: IBR part number (e.g. '4134613')
        execution_time_seconds: total wall-clock time for the pipeline
        defect_count: number of defects detected
        disposition: overall disposition (SERVICEABLE / BLEND / REPLACE)
        phase_timings: optional dict of phase_name -> seconds
    """
    now = datetime.now(timezone.utc)
    dims = _base_dimensions(part_number)

    metric_data = [
        {
            "MetricName": "PipelineExecutionTime",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": execution_time_seconds,
            "Unit": "Seconds",
            "StorageResolution": 60,
        },
        {
            "MetricName": "DefectCount",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": defect_count,
            "Unit": "Count",
            "StorageResolution": 60,
        },
        {
            "MetricName": "PipelineSuccess",
            "Dimensions": _base_dimensions(),
            "Timestamp": now,
            "Value": 1,
            "Unit": "Count",
        },
    ]

    disposition_dims = _base_dimensions()
    disposition_dims.append({"Name": "Disposition", "Value": disposition})
    metric_data.append({
        "MetricName": "DispositionCount",
        "Dimensions": disposition_dims,
        "Timestamp": now,
        "Value": 1,
        "Unit": "Count",
    })

    if phase_timings:
        for phase_name, phase_seconds in phase_timings.items():
            phase_dims = _base_dimensions(part_number)
            phase_dims.append({"Name": "Phase", "Value": phase_name})
            metric_data.append({
                "MetricName": "PhaseExecutionTime",
                "Dimensions": phase_dims,
                "Timestamp": now,
                "Value": phase_seconds,
                "Unit": "Seconds",
            })

    logger.info(
        "Publishing pipeline metrics: part=%s time=%.1fs defects=%d disposition=%s",
        part_number, execution_time_seconds, defect_count, disposition,
    )
    return _put_metrics(metric_data)


def publish_pipeline_error(
    part_number: str,
    error_type: str,
    error_message: str,
    phase: Optional[str] = None,
) -> bool:
    """Publish metrics for a pipeline failure.

    Args:
        part_number: IBR part number
        error_type: classification of the error (e.g. 'ValidationError', 'TimeoutError')
        error_message: human-readable error description (sanitized — no geometry data)
        phase: pipeline phase where the error occurred
    """
    now = datetime.now(timezone.utc)
    dims = _base_dimensions(part_number)

    metric_data = [
        {
            "MetricName": "PipelineError",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": 1,
            "Unit": "Count",
        },
        {
            "MetricName": "PipelineSuccess",
            "Dimensions": _base_dimensions(),
            "Timestamp": now,
            "Value": 0,
            "Unit": "Count",
        },
    ]

    error_dims = _base_dimensions()
    error_dims.append({"Name": "ErrorType", "Value": error_type})
    metric_data.append({
        "MetricName": "ErrorByType",
        "Dimensions": error_dims,
        "Timestamp": now,
        "Value": 1,
        "Unit": "Count",
    })

    if phase:
        phase_dims = _base_dimensions()
        phase_dims.append({"Name": "Phase", "Value": phase})
        metric_data.append({
            "MetricName": "ErrorByPhase",
            "Dimensions": phase_dims,
            "Timestamp": now,
            "Value": 1,
            "Unit": "Count",
        })

    logger.error(
        "Publishing error metrics: part=%s type=%s phase=%s msg=%s",
        part_number, error_type, phase, error_message[:200],
    )
    return _put_metrics(metric_data)


def publish_ml_accuracy(
    accuracy: float,
    precision: float,
    recall: float,
    f1_score: float,
    model_version: str,
    sample_count: int,
) -> bool:
    """Publish ML model performance metrics.

    Args:
        accuracy: overall classification accuracy (0.0 - 1.0)
        precision: weighted precision across defect classes
        recall: weighted recall across defect classes
        f1_score: weighted F1 score
        model_version: version identifier for the ML model
        sample_count: number of samples in the evaluation set
    """
    now = datetime.now(timezone.utc)
    dims = _base_dimensions()
    dims.append({"Name": "ModelVersion", "Value": model_version})

    metric_data = [
        {
            "MetricName": "MLAccuracy",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": accuracy * 100.0,
            "Unit": "Percent",
        },
        {
            "MetricName": "MLPrecision",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": precision * 100.0,
            "Unit": "Percent",
        },
        {
            "MetricName": "MLRecall",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": recall * 100.0,
            "Unit": "Percent",
        },
        {
            "MetricName": "MLF1Score",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": f1_score * 100.0,
            "Unit": "Percent",
        },
        {
            "MetricName": "MLEvaluationSamples",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": sample_count,
            "Unit": "Count",
        },
    ]

    logger.info(
        "Publishing ML metrics: accuracy=%.2f%% precision=%.2f%% recall=%.2f%% "
        "f1=%.2f%% model=%s samples=%d",
        accuracy * 100, precision * 100, recall * 100,
        f1_score * 100, model_version, sample_count,
    )
    return _put_metrics(metric_data)


def publish_error_rate(
    window_minutes: int = 15,
    total_executions: int = 0,
    failed_executions: int = 0,
) -> bool:
    """Publish aggregate error rate over a time window.

    Args:
        window_minutes: the observation window in minutes
        total_executions: total pipeline runs in the window
        failed_executions: failed pipeline runs in the window
    """
    now = datetime.now(timezone.utc)
    dims = _base_dimensions()

    rate = (failed_executions / total_executions * 100.0) if total_executions > 0 else 0.0

    metric_data = [
        {
            "MetricName": "ErrorRate",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": rate,
            "Unit": "Percent",
        },
        {
            "MetricName": "TotalExecutions",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": total_executions,
            "Unit": "Count",
        },
        {
            "MetricName": "FailedExecutions",
            "Dimensions": dims,
            "Timestamp": now,
            "Value": failed_executions,
            "Unit": "Count",
        },
    ]

    logger.info(
        "Publishing error rate: %.1f%% (%d/%d) over %d min",
        rate, failed_executions, total_executions, window_minutes,
    )
    return _put_metrics(metric_data)


class PipelineMetricsContext:
    """Context manager that automatically publishes execution metrics.

    Usage:
        with PipelineMetricsContext(part_number="4134613") as ctx:
            result = run_pipeline(...)
            ctx.set_result(
                defect_count=result["total_defects"],
                disposition=result["overall_disposition"],
            )
    """

    def __init__(self, part_number: str):
        self.part_number = part_number
        self.start_time: float = 0
        self.defect_count: int = 0
        self.disposition: str = "UNKNOWN"
        self.phase_timings: dict[str, float] = {}
        self._error: Optional[tuple[str, str, Optional[str]]] = None

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def set_result(self, defect_count: int, disposition: str,
                   phase_timings: Optional[dict[str, float]] = None) -> None:
        self.defect_count = defect_count
        self.disposition = disposition
        if phase_timings:
            self.phase_timings = phase_timings

    def set_error(self, error_type: str, error_message: str,
                  phase: Optional[str] = None) -> None:
        self._error = (error_type, error_message, phase)

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.monotonic() - self.start_time

        if exc_type is not None:
            publish_pipeline_error(
                part_number=self.part_number,
                error_type=exc_type.__name__,
                error_message=str(exc_val)[:500],
                phase=self._error[2] if self._error else None,
            )
            return False

        if self._error:
            publish_pipeline_error(
                part_number=self.part_number,
                error_type=self._error[0],
                error_message=self._error[1][:500],
                phase=self._error[2],
            )
        else:
            publish_pipeline_execution(
                part_number=self.part_number,
                execution_time_seconds=elapsed,
                defect_count=self.defect_count,
                disposition=self.disposition,
                phase_timings=self.phase_timings,
            )

        return False
