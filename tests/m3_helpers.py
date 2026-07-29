from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

from sdaqf.domain.quality import (
    ArtifactReference,
    CandidateIdentity,
    Claim,
    ClaimCriticality,
    ClaimState,
    Confidence,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
)
from sdaqf.domain.requirements import (
    AcceptanceCriterion,
    RequirementBaseline,
    RequirementPriority,
    RequirementRecord,
    RequirementType,
    SourceMetadata,
    SourceTrace,
    TraceLinks,
)

SOURCE_SHA = "A" * 64
BASELINE_ID = "RB-" + ("A" * 16)
HEAD = "1" * 40
REPOSITORY_DIGEST = "D" * 64
UI_SCREENSHOT_PATH = "evidence/ui.png"
UI_TRACE_PATH = "evidence/ui-trace.json"
RELEASE_PUBLICATION_PATHS = tuple(
    sorted(
        {
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "README.md",
            "SECURITY.md",
            "docs/dependencies.md",
            "docs/release-contract.md",
            "pyproject.toml",
            "requirements-dev.lock",
        }
    )
)


def artifact_reference(path: str, content: bytes) -> ArtifactReference:
    return ArtifactReference(
        path=path,
        sha256=hashlib.sha256(content).hexdigest().upper(),
    )


def candidate() -> CandidateIdentity:
    return CandidateIdentity(SOURCE_SHA, HEAD, REPOSITORY_DIGEST)


def valid_png_bytes() -> bytes:
    """Return one structurally valid 1x1 RGB PNG test fixture."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x14\x57\xd9")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def browser_trace_payload() -> dict[str, object]:
    screenshot = artifact_reference(UI_SCREENSHOT_PATH, valid_png_bytes())
    return {
        "schema_version": "1.0",
        "candidate": candidate().to_dict(),
        "observation": {
            "observed_at": "2026-07-29T00:05:00+00:00",
            "observer_id": "OBS-HOST-1",
            "provenance": "host-browser",
            "platform": "windows",
            "browser": "Chromium",
            "command": ["chromium", "--headless", "ui-example"],
            "flows_passed": ["Review evidence"],
            "states_passed": [
                "loading",
                "empty",
                "error",
                "permission-denied",
                "offline",
            ],
            "devices_passed": ["desktop"],
            "viewports": ["1280x720"],
            "keyboard": True,
            "focus_order": True,
            "readability": True,
            "contrast": True,
            "information_structure": True,
            "efficiency": True,
            "offline": True,
            "recovery": True,
            "visual_regression": "NOT_APPLICABLE",
            "visual_regression_reason": "No prior approved baseline exists.",
            "status": "PASS",
            "failures": [],
        },
        "screenshots": [screenshot.to_dict()],
        "execution": {
            "runner_id": "RUN-TEST-1",
            "executable": "chromium",
            "browser_version": "120.0.0-test",
            "returncode": 0,
            "duration_ms": 1,
            "stdout_sha256": hashlib.sha256(b"").hexdigest().upper(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest().upper(),
            "network_mode": "offline",
        },
    }


def install_command() -> list[str]:
    return [
        "python",
        "-I",
        "-m",
        "pip",
        "--isolated",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-index",
        "--no-build-isolation",
        "--no-deps",
        "--target",
        ".sdaqf/install-target",
        ".sdaqf/install-target-source",
    ]


def install_trace_payload() -> dict[str, object]:
    empty_digest = hashlib.sha256(b"").hexdigest().upper()
    return {
        "schema_version": "1.0",
        "trace_type": "bounded-subprocess-v1",
        "command": install_command(),
        "returncode": 0,
        "started_at": "2026-07-29T00:00:00+00:00",
        "finished_at": "2026-07-29T00:00:01+00:00",
        "duration_ms": 1_000,
        "executable_sha256": "E" * 64,
        "python_version": "3.12.0",
        "stdout_sha256": empty_digest,
        "stderr_sha256": empty_digest,
        "network_mode": "offline",
        "target": ".sdaqf/install-target",
        "target_preexisting": False,
        "source": ".sdaqf/install-target-source",
        "source_preexisting": False,
        "source_repository_digest": REPOSITORY_DIGEST,
        "execution_command": [
            "python",
            "-I",
            "-S",
            "-c",
            (
                "import importlib.util,pathlib,runpy,sys;"
                "t=pathlib.Path('.sdaqf/install-target').resolve();"
                "sys.path.insert(0,str(t));"
                "s=importlib.util.find_spec('sdaqf');"
                "assert s is not None and s.origin is not None "
                "and pathlib.Path(s.origin).resolve().is_relative_to(t);"
                "sys.argv=['sdaqf','--help'];"
                "runpy.run_module('sdaqf',run_name='__main__')"
            ),
        ],
        "execution_returncode": 0,
        "execution_duration_ms": 100,
        "execution_stdout_sha256": empty_digest,
        "execution_stderr_sha256": empty_digest,
        "git_head": HEAD,
        "repository_digest": REPOSITORY_DIGEST,
    }


def materialize_release_source(
    root: Path,
    publication_paths: tuple[str, ...] = RELEASE_PUBLICATION_PATHS,
) -> Path:
    """Create the exact publication-only install source used by test fixtures."""

    source = root / ".sdaqf" / "install-target-source"
    source.mkdir(parents=True)
    for relative in publication_paths:
        original = root / relative
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    return source


def write_evidence_artifacts(root: Path) -> None:
    values = {
        "review/diff.txt": b"diff reviewed\n",
        "review/conformance.txt": b"conformance reviewed\n",
        "evidence/static.txt": b"ruff passed\n",
        UI_SCREENSHOT_PATH: valid_png_bytes(),
        UI_TRACE_PATH: json.dumps(browser_trace_payload(), indent=2).encode(),
    }
    trace = json.dumps(install_trace_payload(), indent=2).encode()
    values["evidence/install-trace.json"] = trace
    for relative, content in values.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def baseline() -> RequirementBaseline:
    criterion = AcceptanceCriterion(
        criterion_id="AC-FR-APP-001-01",
        statement="The input is validated by a test.",
        verification_methods=("test",),
    )
    requirement = RequirementRecord(
        requirement_id="FR-APP-001",
        title="Validate input",
        requirement_type=RequirementType.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        source=SourceTrace(
            document="specification.md",
            section="Functional requirements",
            line_start=1,
            line_end=1,
            excerpt="The command must validate input.",
            derivation_basis="Explicit source identifier.",
        ),
        statement="The command must validate input.",
        acceptance_criteria=(criterion,),
        verification_methods=("test",),
        assumptions=(),
        open_questions=(),
        trace_links=TraceLinks(),
        identifier_source="explicit",
        status="verified",
    )
    return RequirementBaseline(
        baseline_id=BASELINE_ID,
        source=SourceMetadata(
            filename="specification.md",
            path="specification.md",
            sha256=SOURCE_SHA,
            size_bytes=1,
            modified_at="2026-07-29T00:00:00+00:00",
            imported_at="2026-07-29T00:00:00+00:00",
        ),
        requirements=(requirement,),
        source_acceptance_criteria=(),
        diagnostics=(),
    )


def ledger(*, head: str = HEAD) -> EvidenceLedger:
    claim = Claim(
        claim_id="CLM-FR-APP-001",
        statement="FR-APP-001 is implemented and verified.",
        requirement_ids=("FR-APP-001",),
        acceptance_criteria=("AC-FR-APP-001-01",),
        state=ClaimState.VERIFIED,
        criticality=ClaimCriticality.MUST,
        confidence=Confidence.A,
    )
    review = EvidenceRecord(
        evidence_id="EV-DIFF-0001",
        claim_ids=(claim.claim_id,),
        evidence_type=EvidenceType.SOURCE_REVIEW,
        status=EvidenceStatus.PASS,
        command=("git", "diff", "--check"),
        environment=(("os", "test"),),
        commit=head,
        repository_digest=REPOSITORY_DIGEST,
        artifacts=(artifact_reference("review/diff.txt", b"diff reviewed\n"),),
        recorded_at="2026-07-29T00:00:00+00:00",
    )
    install = EvidenceRecord(
        evidence_id="EV-INSTALL-0001",
        claim_ids=(claim.claim_id,),
        evidence_type=EvidenceType.TEST,
        status=EvidenceStatus.PASS,
        command=tuple(install_command()),
        environment=(("os", "test"),),
        commit=head,
        repository_digest=REPOSITORY_DIGEST,
        artifacts=(
            artifact_reference(
                "evidence/install-trace.json",
                json.dumps(install_trace_payload(), indent=2).encode(),
            ),
        ),
        recorded_at="2026-07-29T00:01:00+00:00",
    )
    manual = EvidenceRecord(
        evidence_id="EV-REVIEW-0001",
        claim_ids=(claim.claim_id,),
        evidence_type=EvidenceType.MANUAL_REVIEW,
        status=EvidenceStatus.PASS,
        command=(
            "python",
            "-m",
            "sdaqf",
            "gate",
            "implementation",
            "baseline.json",
            "--ledger",
            "ledger.json",
        ),
        environment=(("os", "test"),),
        commit=head,
        repository_digest=REPOSITORY_DIGEST,
        artifacts=(
            artifact_reference(
                "review/conformance.txt",
                b"conformance reviewed\n",
            ),
        ),
        recorded_at="2026-07-29T00:02:00+00:00",
    )
    return EvidenceLedger(
        baseline_id=BASELINE_ID,
        source_spec_sha256=SOURCE_SHA,
        git_head=head,
        repository_digest=REPOSITORY_DIGEST,
        claims=(claim,),
        evidence=(review, install, manual),
        diff_review_evidence_id=review.evidence_id,
    )


def ledger_payload(*, head: str = HEAD) -> dict[str, Any]:
    return ledger(head=head).to_dict()


def evidence_addition_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "evidence_id": "EV-STATIC-0001",
        "claim_ids": ["CLM-FR-APP-001"],
        "type": "STATIC_ANALYSIS",
        "status": "PASS",
        "command": ["python", "-m", "ruff", "check", "src", "tests", "scripts"],
        "environment": {"os": "test"},
        "commit": HEAD,
        "repository_digest": REPOSITORY_DIGEST,
        "artifacts": [
            artifact_reference("evidence/static.txt", b"ruff passed\n").to_dict()
        ],
        "recorded_at": "2026-07-29T00:03:00+00:00",
    }


def review_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "review_id": "REV-M3-0001",
        "baseline_id": BASELINE_ID,
        "candidate": candidate().to_dict(),
        "reviewed_at": "2026-07-29T00:04:00+00:00",
        "reviewer_id": "AGT-REVIEWER-1",
        "reviewed_agent_ids": ["AGT-IMPLEMENTER-1"],
        "status": "completed",
        "read_only": True,
        "areas": ["regression", "security", "maintainability"],
        "findings": [],
        "reviewed_paths": ["src/sdaqf/application/quality_gates.py"],
        "changed_paths": [],
    }


def ui_payload(*, present: bool = False) -> dict[str, object]:
    if not present:
        return {
            "schema_version": "1.0",
            "project_id": "example-project",
            "ui_present": False,
            "candidate": candidate().to_dict(),
            "design_brief": None,
            "observations": [],
        }
    return {
        "schema_version": "1.0",
        "project_id": "example-project",
        "ui_present": True,
        "candidate": candidate().to_dict(),
        "design_brief": {
            "users": ["Owner"],
            "primary_flows": ["Review evidence"],
            "states": ["loading", "empty", "error", "permission-denied", "offline"],
            "target_devices": ["desktop"],
            "design_research": ["Approved specification and platform guidance."],
            "third_party_asset_policy": "none-used",
            "third_party_asset_provenance": [],
        },
        "observations": [
            {
                "attempt": 1,
                "observed_at": "2026-07-29T00:05:00+00:00",
                "observer_id": "OBS-HOST-1",
                "provenance": "host-browser",
                "platform": "windows",
                "browser": "Chromium",
                "command": ["chromium", "--headless", "ui-example"],
                "flows_passed": ["Review evidence"],
                "states_passed": [
                    "loading",
                    "empty",
                    "error",
                    "permission-denied",
                    "offline",
                ],
                "devices_passed": ["desktop"],
                "viewports": ["1280x720"],
                "keyboard": True,
                "focus_order": True,
                "readability": True,
                "contrast": True,
                "information_structure": True,
                "efficiency": True,
                "offline": True,
                "recovery": True,
                "screenshots": [
                    artifact_reference(
                        UI_SCREENSHOT_PATH,
                        valid_png_bytes(),
                    ).to_dict()
                ],
                "trace": artifact_reference(
                    UI_TRACE_PATH,
                    json.dumps(browser_trace_payload(), indent=2).encode(),
                ).to_dict(),
                "visual_regression": "NOT_APPLICABLE",
                "visual_regression_reason": "No prior approved baseline exists.",
                "status": "PASS",
                "failures": [],
            }
        ],
    }


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
