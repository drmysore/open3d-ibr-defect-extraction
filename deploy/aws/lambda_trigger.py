"""AWS Lambda handler — triggers IBR defect extraction pipeline from S3 upload.

Author: Supreeth Mysore
Program: F135 | Classification: ITAR

ITAR NOTICE: This function processes technical data subject to the International
Traffic in Arms Regulations (ITAR), 22 CFR Parts 120-130. Access is restricted
to U.S. Persons as defined in 22 CFR 120.15. This Lambda MUST execute in
ITAR-compliant AWS regions (us-east-1, us-west-2). Unauthorized export or
transfer of this technical data is prohibited.

Trigger: S3 PutObject on PLY files matching pattern scan_{part_number}.ply
Actions:
  1. Validate ITAR region compliance
  2. Extract part_number from filename
  3. Locate corresponding CAD reference file
  4. Start Step Functions execution
  5. Publish SNS notification
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ITAR_ALLOWED_REGIONS = frozenset({"us-east-1", "us-west-2"})
SCAN_FILENAME_PATTERN = re.compile(r"^scan_([A-Za-z0-9\-]+)\.ply$")
CAD_PREFIX_TEMPLATE = "cad_{part_number}.ply"
PROGRAM_ID = "F135"

STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class ITARRegionViolationError(Exception):
    """Raised when Lambda executes outside an ITAR-compliant region."""


class InvalidFilenameError(Exception):
    """Raised when the uploaded file does not match the expected naming pattern."""


class MissingCADReferenceError(Exception):
    """Raised when the corresponding CAD PLY file is not found in S3."""


def _validate_itar_region(region: str) -> None:
    if region not in ITAR_ALLOWED_REGIONS:
        raise ITARRegionViolationError(
            f"Region '{region}' is not ITAR-compliant. "
            f"Allowed regions: {sorted(ITAR_ALLOWED_REGIONS)}. "
            f"This Lambda processes F135 technical data subject to ITAR 22 CFR 120-130."
        )


def _extract_part_number(filename: str) -> str:
    basename = os.path.basename(filename)
    match = SCAN_FILENAME_PATTERN.match(basename)
    if not match:
        raise InvalidFilenameError(
            f"Filename '{basename}' does not match expected pattern 'scan_{{part_number}}.ply'. "
            f"Examples: scan_4134613.ply, scan_4131129-01.ply"
        )
    return match.group(1)


def _verify_cad_exists(s3_client: Any, bucket: str, part_number: str) -> str:
    cad_key = f"data/{CAD_PREFIX_TEMPLATE.format(part_number=part_number)}"
    try:
        s3_client.head_object(Bucket=bucket, Key=cad_key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            raise MissingCADReferenceError(
                f"CAD reference file not found: s3://{bucket}/{cad_key}. "
                f"Upload the CAD PLY before the scan file."
            )
        raise
    return cad_key


def _start_step_functions(sfn_client: Any, scan_key: str, cad_key: str,
                          bucket: str, part_number: str) -> dict:
    execution_name = f"ibr-{part_number}-{int(time.time())}"
    input_payload = {
        "bucket": bucket,
        "scan_key": scan_key,
        "cad_key": cad_key,
        "part_number": part_number,
        "program": PROGRAM_ID,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "trigger_source": "s3_upload",
    }

    response = sfn_client.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=execution_name,
        input=json.dumps(input_payload),
    )

    logger.info(
        "Started Step Functions execution: %s (ARN: %s)",
        execution_name,
        response["executionArn"],
    )
    return {
        "execution_arn": response["executionArn"],
        "execution_name": execution_name,
    }


def _publish_sns_notification(sns_client: Any, part_number: str,
                              bucket: str, scan_key: str,
                              execution_info: dict) -> None:
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN not configured — skipping notification")
        return

    message = {
        "event": "pipeline_triggered",
        "program": PROGRAM_ID,
        "classification": "ITAR",
        "part_number": part_number,
        "source_bucket": bucket,
        "scan_file": scan_key,
        "execution_arn": execution_info["execution_arn"],
        "execution_name": execution_info["execution_name"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"IBR Pipeline Triggered — Part {part_number}",
            Message=json.dumps(message, indent=2),
            MessageAttributes={
                "program": {"DataType": "String", "StringValue": PROGRAM_ID},
                "classification": {"DataType": "String", "StringValue": "ITAR"},
                "event_type": {"DataType": "String", "StringValue": "pipeline_triggered"},
            },
        )
        logger.info("SNS notification published for part %s", part_number)
    except ClientError:
        logger.exception("Failed to publish SNS notification for part %s", part_number)


def handler(event: dict, context: Any) -> dict:
    """Lambda entry point — triggered by S3 PutObject on PLY files.

    Expected event structure (S3 notification):
    {
        "Records": [{
            "s3": {
                "bucket": {"name": "..."},
                "object": {"key": "data/scan_4134613.ply", "size": ...}
            },
            "awsRegion": "us-east-1"
        }]
    }
    """
    logger.info("Lambda invoked with %d record(s)", len(event.get("Records", [])))

    _validate_itar_region(AWS_REGION)

    results = []

    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        object_key = s3_info.get("object", {}).get("key", "")
        event_region = record.get("awsRegion", AWS_REGION)

        logger.info("Processing: s3://%s/%s (region: %s)", bucket, object_key, event_region)

        _validate_itar_region(event_region)

        if not object_key.lower().endswith(".ply"):
            logger.info("Skipping non-PLY file: %s", object_key)
            continue

        filename = os.path.basename(object_key)
        if not SCAN_FILENAME_PATTERN.match(filename):
            logger.info("Skipping file that doesn't match scan pattern: %s", filename)
            continue

        try:
            part_number = _extract_part_number(object_key)
            logger.info("Extracted part_number: %s from %s", part_number, object_key)

            s3_client = boto3.client("s3", region_name=AWS_REGION)
            cad_key = _verify_cad_exists(s3_client, bucket, part_number)
            logger.info("CAD reference verified: s3://%s/%s", bucket, cad_key)

            sfn_client = boto3.client("stepfunctions", region_name=AWS_REGION)
            execution_info = _start_step_functions(
                sfn_client, object_key, cad_key, bucket, part_number
            )

            sns_client = boto3.client("sns", region_name=AWS_REGION)
            _publish_sns_notification(
                sns_client, part_number, bucket, object_key, execution_info
            )

            results.append({
                "status": "triggered",
                "part_number": part_number,
                "scan_key": object_key,
                "cad_key": cad_key,
                "execution_arn": execution_info["execution_arn"],
            })

        except (InvalidFilenameError, MissingCADReferenceError) as exc:
            logger.error("Validation failed for %s: %s", object_key, exc)
            results.append({
                "status": "validation_error",
                "scan_key": object_key,
                "error": str(exc),
            })

        except ITARRegionViolationError as exc:
            logger.critical("ITAR VIOLATION: %s", exc)
            raise

        except ClientError as exc:
            logger.exception("AWS API error processing %s", object_key)
            results.append({
                "status": "aws_error",
                "scan_key": object_key,
                "error": str(exc),
            })

    response = {
        "statusCode": 200,
        "body": {
            "processed": len(results),
            "results": results,
            "program": PROGRAM_ID,
            "region": AWS_REGION,
        },
    }

    logger.info("Lambda complete: %d file(s) processed", len(results))
    return response
