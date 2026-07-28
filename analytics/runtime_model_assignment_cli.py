"""Bounded trusted-host adapter for governed p2-v3 model assignment."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

from runtime_model_lifecycle_commit import commit_lifecycle_action


_SAFE_ERROR = re.compile(r"^[a-z0-9_]{1,120}$")


class _BoundedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("invalid_assignment_cli_request")


def _bounded_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"invalid_{field}")
    return normalized


def _uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid_approved_forecast_run_id") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise argparse.ArgumentTypeError("invalid_approved_forecast_run_id")
    return str(parsed)


def _absolute_directory(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("configured_root_must_be_absolute")
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = _BoundedParser(add_help=False)
    parser.add_argument("--approved-forecast-run-id", required=True, type=_uuid4)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--acknowledgement", required=True, choices=("true",))
    parser.add_argument("--runtime-root", required=True, type=_absolute_directory)
    parser.add_argument("--repository-root", required=True, type=_absolute_directory)
    parser.add_argument("--operator-identifier", required=True)
    return parser


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    reason = _bounded_text(arguments.reason, "reason", 1000)
    operator = _bounded_text(arguments.operator_identifier, "operator_identifier", 128)
    if arguments.acknowledgement != "true":
        raise ValueError("invalid_acknowledgement")
    result = commit_lifecycle_action(
        runtime_root=arguments.runtime_root,
        one_run_forecast_run_id=arguments.approved_forecast_run_id,
        reason=reason,
        operator_identifier=operator,
        acknowledgement=arguments.acknowledgement == "true",
        repository_root=arguments.repository_root,
    )
    if result.get("success") is not True:
        code = str(result.get("error", "assignment_publication_failed"))
        return {
            "ok": False,
            "code": code if _SAFE_ERROR.fullmatch(code) else "assignment_publication_failed",
        }
    return {
        "ok": True,
        "assignmentId": str(result["assignmentId"]),
        "selectedCandidateId": str(result["modelId"]),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        result = execute(arguments)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["ok"] is True else 1
    except (argparse.ArgumentError, ValueError):
        print('{"code":"invalid_assignment_cli_request","ok":false}')
        return 2
    except SystemExit:
        print('{"code":"invalid_assignment_cli_request","ok":false}')
        return 2
    except Exception:
        print('{"code":"assignment_publication_failed","ok":false}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
