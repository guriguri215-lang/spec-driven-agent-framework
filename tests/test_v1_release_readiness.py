from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.gates import GateEngine
from sdaqf.application.quality_gates import parse_independent_review
from sdaqf.application.release_qa import (
    PublicationReadinessService,
    load_publication_readiness,
    load_release_candidate,
)
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import GitObservation
from tests.m3_helpers import (
    BASELINE_ID,
    HEAD,
    REPOSITORY_DIGEST,
    SOURCE_SHA,
    baseline,
    ledger,
    review_payload,
    write_json,
)
from tests.test_v1_license import LICENSE_SHA256, NOTICE_SHA256


def publication_payload(
    *,
    paths: tuple[str, ...],
    notes_sha256: str,
    gate_digests: dict[str, str] | None = None,
) -> dict[str, object]:
    digests = gate_digests or {
        gate_id: "B" * 64 for gate_id in ("G1", "G2", "G3", "G4")
    }
    identity = {
        "source_spec_sha256": SOURCE_SHA,
        "git_head": HEAD,
        "repository_digest": REPOSITORY_DIGEST,
    }
    return {
        "schema_version": "1.0",
        "candidate": {
            "identity": identity,
            "branch": "main",
            "publication_paths": list(paths),
        },
        "project": {
            "name": "SDAQF",
            "repository": "spec-driven-agent-framework",
            "distribution": "sdaqf",
            "cli": "sdaqf",
            "version": "1.0.0rc1",
            "proposed_tag": "v1.0.0-rc.1",
            "desired_visibility": "PUBLIC",
            "default_branch": "main",
            "target_public_api": "1.0.0",
        },
        "license": license_payload(),
        "release": {
            "level": "release-candidate-prerelease",
            "audience": ["framework evaluators", "advanced Codex users"],
            "title": "SDAQF v1.0.0-rc.1",
            "description": (
                "Offline-first specification-driven development and quality "
                "assurance for Codex-assisted projects."
            ),
            "notes": {
                "path": "docs/releases/v1.0.0-rc.1.md",
                "sha256": notes_sha256,
            },
            "prerelease": True,
            "latest": False,
            "attached_assets": [],
            "package_registry_publication": False,
            "source_archives": "GitHub-provided tag archives only",
        },
        "policies": {
            "compatibility": (
                "Target V1 public API; prerelease compatibility is not guaranteed "
                "until 1.0.0."
            ),
            "migration": (
                "No migration is required from the M4 Public Beta CLI; validate "
                "versioned schemas before reuse."
            ),
            "rollback": (
                "Discard the unpublished local candidate; never delete or move a "
                "published tag automatically."
            ),
            "support": (
                "GitHub Issues for bugs and documentation; best effort, no SLA, "
                "latest release only."
            ),
            "security": (
                "Use GitHub private vulnerability reporting after separately approved "
                "enablement when public; do not disclose vulnerabilities in public issues."
            ),
            "maintenance": (
                "No prerelease backports; final 1.0.0 receives best-effort Critical "
                "security and data-loss fixes for six months."
            ),
            "contributions": (
                "External pull requests are not accepted during the release candidate; "
                "bug and documentation issues are best effort."
            ),
            "code_of_conduct": "DEFERRED_UNTIL_OPEN_CONTRIBUTIONS",
            "known_limitations": [
                "Release candidate; not for production use.",
                "macOS is not verified.",
                "OpenAI API or Agents SDK adapter is deferred post-V1.",
                "Management UI is deferred post-V1.",
                (
                    "Authored comparison is not empirical, causal, blinded, randomized, "
                    "independently replicated, statistically powered, or cost-comparable."
                ),
            ],
        },
        "verification": {
            "gates": {
                gate_id: {
                    "status": "PASS",
                    "evidence": {
                        "path": f".sdaqf/v1/gates/{gate_id}.json",
                        "sha256": digests[gate_id],
                    },
                }
                for gate_id in ("G1", "G2", "G3", "G4")
            },
            "independent_review": {
                "baseline_id": BASELINE_ID,
                "candidate": identity,
                "decision": "GO",
                "unresolved_findings": {
                    "Critical": 0,
                    "High": 0,
                    "Medium": 0,
                    "Low": 0,
                },
            },
            "required_matrix": [
                "windows-python-3.12",
                "windows-python-3.13",
                "linux-python-3.12",
                "linux-python-3.13",
            ],
            "macos": "NOT_VERIFIED",
        },
        "publication_performed": False,
        "actual_gate_g5": "NOT_RUN",
    }


def license_payload() -> dict[str, object]:
    return {
        "spdx_expression": "Apache-2.0",
        "copyright_holder": "guriguri215-lang",
        "license_file": {"path": "LICENSE", "sha256": LICENSE_SHA256},
        "notice_file": {"path": "NOTICE", "sha256": NOTICE_SHA256},
    }


def release_candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "install_evidence_id": "EV-INSTALL-0001",
        "execution_module": "sdaqf",
        "install_target": ".sdaqf/install-target",
        "rollback_guidance": (
            "Remove only the owned .sdaqf/install-target and "
            ".sdaqf/install-target-source directories."
        ),
        "documentation_paths": [
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "README.md",
            "SECURITY.md",
            "docs/release-contract.md",
        ],
        "license": license_payload(),
    }


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("project", "version"), "1.0.0"),
        (("project", "proposed_tag"), "v1.0.0"),
        (("release", "latest"), True),
        (("publication_performed",), True),
        (("actual_gate_g5",), "PASS"),
        (("verification", "macos"), "PASS"),
        (
            ("verification", "gates", "G4", "evidence", "path"),
            ".sdaqf/v1/gates/other.json",
        ),
    ),
)
def test_publication_loader_fails_closed_on_approved_boundary_mismatch(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    payload = publication_payload(
        paths=("docs/releases/v1.0.0-rc.1.md",),
        notes_sha256="A" * 64,
    )
    target: dict[str, object] = payload
    for component in path[:-1]:
        target = target[component]  # type: ignore[assignment]
    target[path[-1]] = value

    with pytest.raises(ContractError):
        load_publication_readiness(write_json(tmp_path / "candidate.json", payload))


def test_publication_readiness_is_local_ready_and_never_gate_g5(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "docs" / "releases").mkdir(parents=True)
    repository = Path(__file__).resolve().parents[1]
    (root / "LICENSE").write_bytes((repository / "LICENSE").read_bytes())
    (root / "NOTICE").write_bytes((repository / "NOTICE").read_bytes())
    notes = root / "docs" / "releases" / "v1.0.0-rc.1.md"
    notes.write_text("# Local release notes\n", encoding="utf-8")
    (root / "docs" / "dependencies.md").write_text(
        "# Dependency licenses\n\npytest: MIT\n",
        encoding="utf-8",
    )
    (root / "requirements-dev.lock").write_text("pytest==9.0.2\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies = []\nlicense = "Apache-2.0"\n'
        'license-files = ["LICENSE", "NOTICE"]\n',
        encoding="utf-8",
    )
    paths = tuple(
        sorted(
            (
                "LICENSE",
                "NOTICE",
                "docs/dependencies.md",
                "docs/releases/v1.0.0-rc.1.md",
                "pyproject.toml",
                "requirements-dev.lock",
            )
        )
    )
    gates = {
        "G1": _passing_gate("G1"),
        "G2": _passing_gate("G2"),
        "G3": _passing_gate("G3"),
        "G4": _passing_g4_gate(),
    }
    gate_candidate = {
        "source_spec_sha256": SOURCE_SHA,
        "git_head": HEAD,
        "repository_digest": REPOSITORY_DIGEST,
    }
    gate_digests: dict[str, str] = {}
    for gate_id, gate in gates.items():
        gate_path = root / ".sdaqf" / "v1" / "gates" / f"{gate_id}.json"
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "candidate": gate_candidate,
                    "result": gate.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        gate_digests[gate_id] = hashlib.sha256(
            gate_path.read_bytes()
        ).hexdigest().upper()
    declaration = load_publication_readiness(
        write_json(
            tmp_path / "public.json",
            publication_payload(
                paths=paths,
                notes_sha256=hashlib.sha256(notes.read_bytes()).hexdigest().upper(),
                gate_digests=gate_digests,
            ),
        )
    )
    candidate = load_release_candidate(
        write_json(tmp_path / "release.json", release_candidate_payload())
    )
    review_data = copy.deepcopy(review_payload())
    review = parse_independent_review(review_data)
    result = PublicationReadinessService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=review,
        declaration=declaration,
        release_candidate=candidate,
        g1=gates["G1"],
        g2=gates["G2"],
        g3=gates["G3"],
        git=GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            publication_paths=paths,
        ),
    )

    assert result.gate_id == "G5-LOCAL-READINESS"
    assert result.passed
    assert declaration.publication_performed is False
    assert declaration.actual_gate_g5 == "NOT_RUN"

    g4_path = root / ".sdaqf" / "v1" / "gates" / "G4.json"
    wrong_g4 = json.loads(g4_path.read_text(encoding="utf-8"))
    wrong_g4["candidate"]["git_head"] = "2" * 40
    g4_path.write_text(
        json.dumps(wrong_g4, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    wrong_gate_digests = dict(gate_digests)
    wrong_gate_digests["G4"] = hashlib.sha256(g4_path.read_bytes()).hexdigest().upper()
    wrong_declaration = load_publication_readiness(
        write_json(
            tmp_path / "wrong-public.json",
            publication_payload(
                paths=paths,
                notes_sha256=hashlib.sha256(notes.read_bytes()).hexdigest().upper(),
                gate_digests=wrong_gate_digests,
            ),
        )
    )
    changed = PublicationReadinessService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=review,
        declaration=wrong_declaration,
        release_candidate=candidate,
        g1=gates["G1"],
        g2=gates["G2"],
        g3=gates["G3"],
        git=GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            publication_paths=paths,
        ),
    )
    assert "LOCAL-GATES-G1-G4" in changed.hard_blockers

    incomplete_g4 = {
        "schema_version": "1.0",
        "candidate": gate_candidate,
        "result": _passing_gate("G4").to_dict(),
    }
    g4_path.write_text(
        json.dumps(incomplete_g4, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    incomplete_digests = dict(gate_digests)
    incomplete_digests["G4"] = hashlib.sha256(g4_path.read_bytes()).hexdigest().upper()
    incomplete_declaration = load_publication_readiness(
        write_json(
            tmp_path / "incomplete-public.json",
            publication_payload(
                paths=paths,
                notes_sha256=hashlib.sha256(notes.read_bytes()).hexdigest().upper(),
                gate_digests=incomplete_digests,
            ),
        )
    )
    incomplete = PublicationReadinessService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=review,
        declaration=incomplete_declaration,
        release_candidate=candidate,
        g1=gates["G1"],
        g2=gates["G2"],
        g3=gates["G3"],
        git=GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            publication_paths=paths,
        ),
    )
    assert "LOCAL-GATES-G1-G4" in incomplete.hard_blockers

    compensating_g4: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate": gate_candidate,
        "result": gates["G4"].to_dict(),
    }
    compensating_g4["result"]["checks"][0]["hard_blocker"] = False
    g4_path.write_text(
        json.dumps(compensating_g4, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    compensating_digests = dict(gate_digests)
    compensating_digests["G4"] = hashlib.sha256(
        g4_path.read_bytes()
    ).hexdigest().upper()
    compensating_declaration = load_publication_readiness(
        write_json(
            tmp_path / "compensating-public.json",
            publication_payload(
                paths=paths,
                notes_sha256=hashlib.sha256(notes.read_bytes()).hexdigest().upper(),
                gate_digests=compensating_digests,
            ),
        )
    )
    compensating = PublicationReadinessService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=review,
        declaration=compensating_declaration,
        release_candidate=candidate,
        g1=gates["G1"],
        g2=gates["G2"],
        g3=gates["G3"],
        git=GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            publication_paths=paths,
        ),
    )
    assert "LOCAL-GATES-G1-G4" in compensating.hard_blockers


def _passing_gate(gate_id: str) -> GateResult:
    return GateEngine().evaluate(
        gate_id,
        (GateCheck("PASS", True, True, "passed"),),
    )


def _passing_g4_gate() -> GateResult:
    check_ids = (
        "G4-PRIOR-GATES",
        "G4-REPRODUCIBLE-INSTALL",
        "G4-MUST-VERIFIED",
        "G4-SECURITY-AUDIT",
        "G4-DEPENDENCY-LICENSE",
        "G4-DOCUMENTATION",
        "G4-ROLLBACK",
        "G4-GIT",
    )
    return GateEngine().evaluate(
        "G4",
        tuple(
            GateCheck(check_id, True, True, "passed")
            for check_id in check_ids
        ),
    )
