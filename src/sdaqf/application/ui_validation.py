"""Offline validation of UI classification and recorded browser observations."""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    command_argv,
    enum_value,
    integer_value,
    load_json_object,
    object_value,
    only_keys,
    optional_string,
    parse_artifact_reference,
    parse_candidate_identity,
    path_free_text,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    timestamp,
    verify_artifact,
)
from sdaqf.application.gates import GateEngine
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import (
    ArtifactReference,
    BrowserObservation,
    CandidateIdentity,
    DesignBrief,
    EvidenceStatus,
    UiValidation,
)

_PROJECT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OBSERVER_ID = re.compile(r"^OBS-[A-Z0-9][A-Z0-9-]{0,63}$")
_RUNNER_ID = re.compile(r"^RUN-[A-Z0-9][A-Z0-9-]{0,63}$")
_REQUIRED_STATES = {
    "loading",
    "empty",
    "error",
    "permission-denied",
    "offline",
}
_PLATFORMS = {"windows", "linux", "macos"}
_BROWSERS = {"Chromium", "Chrome", "Edge", "Firefox", "Safari", "WebKit"}
_BROWSER_EXECUTABLES = {
    "Chromium": {"chromium", "chromium-browser", "chromium.exe"},
    "Chrome": {"chrome", "chrome.exe", "google-chrome", "google-chrome-stable"},
    "Edge": {"microsoft-edge", "msedge", "msedge.exe"},
    "Firefox": {"firefox", "firefox.exe"},
    "Safari": {"safari"},
    "WebKit": {"playwright-webkit", "webkit"},
}
_BROWSER_VERSION = re.compile(
    r"^[0-9]{1,4}(?:\.[0-9]{1,8}){1,4}"
    r"(?:[-+][A-Za-z0-9][A-Za-z0-9._-]{0,63})?$"
)
_PNG_ANCILLARY_BEFORE_IDAT = {
    b"cHRM",
    b"eXIf",
    b"gAMA",
    b"iCCP",
    b"iTXt",
    b"pHYs",
    b"sBIT",
    b"sRGB",
    b"tEXt",
    b"tIME",
    b"zTXt",
}
_PNG_ANCILLARY_AFTER_IDAT = {b"eXIf", b"iTXt", b"tEXt", b"tIME", b"zTXt"}


@dataclass(frozen=True, slots=True)
class ProjectManifestIdentity:
    """Strictly validated manifest fields used by M3 Gates."""

    project_id: str
    ui_present: bool
    source_filename: str
    source_spec_sha256: str
    required_platforms: tuple[str, ...]
    optional_platforms: tuple[str, ...]


def load_manifest_ui(path: Path) -> ProjectManifestIdentity:
    """Load and validate the full canonical project manifest."""

    root = load_json_object(path, "Project manifest", maximum_bytes=64 * 1024)
    only_keys(
        root,
        {
            "schema_version",
            "project_id",
            "title",
            "release_level",
            "source_spec",
            "platforms",
            "ui",
            "network_policy",
            "api_required",
        },
        "manifest",
    )
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("Manifest schema_version must be 1.0.")
    project_id = string_value(root.get("project_id"), "project_id", maximum=100)
    if not _PROJECT_ID.fullmatch(project_id):
        raise ContractError("project_id must use lowercase ASCII words.")
    path_free_text(root.get("title"), "title", maximum=200)
    path_free_text(root.get("release_level"), "release_level", maximum=100)
    source = object_value(root.get("source_spec"), "source_spec")
    only_keys(source, {"filename", "sha256", "imported_at"}, "source_spec")
    filename = safe_relative_path(source.get("filename"), "source_spec.filename")
    if "/" in filename:
        raise ContractError("source_spec.filename must be a filename.")
    source_digest = sha256(source.get("sha256"), "source_spec.sha256")
    timestamp(source.get("imported_at"), "source_spec.imported_at")
    platforms = object_value(root.get("platforms"), "platforms")
    only_keys(platforms, {"required", "optional"}, "platforms")
    required = string_tuple(
        platforms.get("required"),
        "platforms.required",
        minimum=1,
        maximum=3,
    )
    optional = string_tuple(
        platforms.get("optional"),
        "platforms.optional",
        maximum=3,
    )
    if not set((*required, *optional)) <= _PLATFORMS:
        raise ContractError("platforms contains an unsupported platform.")
    if set(required) & set(optional):
        raise ContractError("required and optional platforms must not overlap.")
    ui = object_value(root.get("ui"), "ui")
    only_keys(ui, {"present"}, "ui")
    network_policy = string_value(
        root.get("network_policy"),
        "network_policy",
        maximum=20,
    )
    if network_policy not in {"default-deny", "restricted", "allowed"}:
        raise ContractError("network_policy is unsupported.")
    boolean_value(root.get("api_required"), "api_required")
    return ProjectManifestIdentity(
        project_id=project_id,
        ui_present=boolean_value(ui.get("present"), "ui.present"),
        source_filename=filename,
        source_spec_sha256=source_digest,
        required_platforms=required,
        optional_platforms=optional,
    )


def load_ui_validation(path: Path) -> UiValidation:
    """Load one bounded UI validation record."""

    return parse_ui_validation(load_json_object(path, "UI validation"))


def parse_ui_validation(payload: object) -> UiValidation:
    """Validate a decoded UI validation record."""

    root = object_value(payload, "ui_validation")
    only_keys(
        root,
        {
            "schema_version",
            "project_id",
            "ui_present",
            "candidate",
            "design_brief",
            "observations",
        },
        "ui_validation",
    )
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("schema_version must be 1.0.")
    project_id = string_value(root.get("project_id"), "project_id", maximum=100)
    if not _PROJECT_ID.fullmatch(project_id):
        raise ContractError("project_id must use lowercase ASCII words.")
    ui_present = boolean_value(root.get("ui_present"), "ui_present")
    brief = (
        None
        if root.get("design_brief") is None
        else _parse_design_brief(root.get("design_brief"))
    )
    observations = tuple(
        _parse_observation(value, index)
        for index, value in enumerate(
            array_value(root.get("observations"), "observations", maximum=3)
        )
    )
    if ui_present:
        if brief is None:
            raise ContractError("A UI project requires a Design Brief.")
        if not observations:
            raise ContractError("A UI project requires a browser observation.")
        attempts = tuple(item.attempt for item in observations)
        if attempts != tuple(range(1, len(observations) + 1)):
            raise ContractError("UI observations must use consecutive attempt numbers.")
    elif brief is not None or observations:
        raise ContractError("A non-UI project must not fabricate UI validation evidence.")
    return UiValidation(
        project_id=project_id,
        ui_present=ui_present,
        candidate=parse_candidate_identity(root.get("candidate"), "candidate"),
        design_brief=brief,
        observations=observations,
    )


class UiValidationService:
    """Evaluate UI/UX evidence without launching or installing a browser."""

    def evaluate(
        self,
        *,
        manifest: ProjectManifestIdentity,
        candidate: CandidateIdentity,
        validation: UiValidation,
        root: Path,
    ) -> GateResult:
        """Return a fail-closed UI validation result."""

        identity = (
            validation.project_id == manifest.project_id
            and validation.ui_present is manifest.ui_present
            and manifest.source_spec_sha256 == candidate.source_spec_sha256
            and validation.candidate == candidate
        )
        if not manifest.ui_present:
            return GateEngine().evaluate(
                "UI",
                (
                    GateCheck(
                        "UI-CLASSIFICATION",
                        identity,
                        True,
                        "Manifest, candidate, and UI classifications match.",
                    ),
                    GateCheck(
                        "UI-NOT-APPLICABLE",
                        validation.design_brief is None and not validation.observations,
                        True,
                        "No browser evidence is fabricated for a non-UI project.",
                    ),
                ),
            )

        brief = validation.design_brief
        latest = validation.observations[-1] if validation.observations else None
        supported_platforms = set(
            (*manifest.required_platforms, *manifest.optional_platforms)
        )
        brief_complete = (
            brief is not None
            and bool(brief.users)
            and bool(brief.primary_flows)
            and set(brief.states) >= _REQUIRED_STATES
            and bool(brief.target_devices)
            and bool(brief.design_research)
            and brief.third_party_asset_policy in {"none-used", "authorized"}
            and (
                (
                    brief.third_party_asset_policy == "none-used"
                    and not brief.third_party_asset_provenance
                )
                or (
                    brief.third_party_asset_policy == "authorized"
                    and bool(brief.third_party_asset_provenance)
                )
            )
        )
        observation_consistent = all(
            item.platform in supported_platforms
            and item.browser in _BROWSERS
            and bool(item.command)
            and bool(item.observer_id)
            and item.provenance in {"host-browser", "target-platform"}
            and all(_valid_image_artifact(root, shot) for shot in item.screenshots)
            and verify_artifact(root, item.trace)
            and _valid_browser_trace(root, item, candidate)
            and (
                (
                    item.status is EvidenceStatus.PASS
                    and not item.failures
                    and all(
                        (
                            item.keyboard,
                            item.focus_order,
                            item.readability,
                            item.contrast,
                            item.information_structure,
                            item.efficiency,
                            item.offline,
                            item.recovery,
                        )
                    )
                )
                or (item.status is EvidenceStatus.FAIL and bool(item.failures))
            )
            for item in validation.observations
        )
        latest_complete = (
            latest is not None
            and brief is not None
            and latest.status is EvidenceStatus.PASS
            and set(brief.primary_flows) <= set(latest.flows_passed)
            and set(brief.states) <= set(latest.states_passed)
            and set(brief.target_devices) <= set(latest.devices_passed)
            and bool(latest.viewports)
            and bool(latest.screenshots)
            and (
                latest.visual_regression == "PASS"
                or (
                    latest.visual_regression == "NOT_APPLICABLE"
                    and latest.visual_regression_reason is not None
                )
            )
        )
        checks = (
            GateCheck(
                "UI-CLASSIFICATION",
                identity,
                True,
                "Manifest, candidate, and UI classifications match.",
            ),
            GateCheck(
                "UI-DESIGN-BRIEF",
                brief_complete,
                True,
                "Users, flows, states, and target devices are required.",
            ),
            GateCheck(
                "UI-BOUNDED-LOOP",
                bool(validation.observations)
                and len(validation.observations) <= 3
                and observation_consistent,
                True,
                "Up to three artifact-backed host validation attempts are accepted.",
            ),
            GateCheck(
                "UI-PRIMARY-FLOWS",
                latest_complete,
                True,
                "The latest attempt must pass flows, states, devices, and screenshots.",
            ),
            GateCheck(
                "UI-ACCESSIBILITY",
                latest is not None
                and all(
                    (
                        latest.keyboard,
                        latest.focus_order,
                        latest.readability,
                        latest.contrast,
                        latest.information_structure,
                        latest.efficiency,
                    )
                ),
                True,
                "Accessibility, information structure, and efficiency must pass.",
            ),
            GateCheck(
                "UI-RECOVERY-OFFLINE",
                latest is not None and latest.recovery and latest.offline,
                True,
                "Recovery and offline behavior must pass.",
            ),
        )
        return GateEngine().evaluate("UI", checks)


def _parse_design_brief(value: object) -> DesignBrief:
    item = object_value(value, "design_brief")
    only_keys(
        item,
        {
            "users",
            "primary_flows",
            "states",
            "target_devices",
            "design_research",
            "third_party_asset_policy",
            "third_party_asset_provenance",
        },
        "design_brief",
    )
    asset_policy = string_value(
        item.get("third_party_asset_policy"),
        "design_brief.third_party_asset_policy",
        maximum=20,
    )
    if asset_policy not in {"none-used", "authorized"}:
        raise ContractError("third_party_asset_policy is unsupported.")
    provenance = string_tuple(
        item.get("third_party_asset_provenance"),
        "design_brief.third_party_asset_provenance",
    )
    if (asset_policy == "none-used" and provenance) or (
        asset_policy == "authorized" and not provenance
    ):
        raise ContractError("Third-party asset policy and provenance are inconsistent.")
    return DesignBrief(
        users=string_tuple(item.get("users"), "design_brief.users", minimum=1),
        primary_flows=string_tuple(
            item.get("primary_flows"),
            "design_brief.primary_flows",
            minimum=1,
        ),
        states=string_tuple(item.get("states"), "design_brief.states", minimum=1),
        target_devices=string_tuple(
            item.get("target_devices"),
            "design_brief.target_devices",
            minimum=1,
        ),
        design_research=string_tuple(
            item.get("design_research"),
            "design_brief.design_research",
            minimum=1,
        ),
        third_party_asset_policy=asset_policy,
        third_party_asset_provenance=provenance,
    )


def _parse_observation(value: object, index: int) -> BrowserObservation:
    where = f"observations[{index}]"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "attempt",
            "observed_at",
            "observer_id",
            "provenance",
            "platform",
            "browser",
            "command",
            "flows_passed",
            "states_passed",
            "devices_passed",
            "viewports",
            "keyboard",
            "focus_order",
            "readability",
            "contrast",
            "information_structure",
            "efficiency",
            "offline",
            "recovery",
            "screenshots",
            "trace",
            "visual_regression",
            "visual_regression_reason",
            "status",
            "failures",
        },
        where,
    )
    status = enum_value(EvidenceStatus, item.get("status"), f"{where}.status")
    if status is EvidenceStatus.NOT_VERIFIED:
        raise ContractError("Browser observation status must be PASS or FAIL.")
    browser = string_value(item.get("browser"), f"{where}.browser", maximum=100)
    if browser not in _BROWSERS:
        raise ContractError("Browser observation must name a supported real browser.")
    observer_id = string_value(
        item.get("observer_id"),
        f"{where}.observer_id",
        maximum=68,
    )
    if not _OBSERVER_ID.fullmatch(observer_id):
        raise ContractError("Browser observer_id is invalid.")
    provenance = string_value(
        item.get("provenance"),
        f"{where}.provenance",
        maximum=20,
    )
    if provenance not in {"host-browser", "target-platform"}:
        raise ContractError("Browser provenance is unsupported.")
    screenshots = tuple(
        parse_artifact_reference(value, f"{where}.screenshots[{shot_index}]")
        for shot_index, value in enumerate(
            array_value(item.get("screenshots"), f"{where}.screenshots", maximum=64)
        )
    )
    paths = tuple(item.path for item in screenshots)
    if len(paths) != len(set(paths)):
        raise ContractError(f"{where}.screenshots must contain unique paths.")
    visual = string_value(
        item.get("visual_regression"),
        f"{where}.visual_regression",
        maximum=20,
    )
    if visual not in {"PASS", "NOT_APPLICABLE"}:
        raise ContractError("visual_regression is unsupported.")
    visual_reason = optional_string(
        item.get("visual_regression_reason"),
        f"{where}.visual_regression_reason",
        maximum=500,
    )
    if (visual == "NOT_APPLICABLE") != (visual_reason is not None):
        raise ContractError(
            "NOT_APPLICABLE visual regression requires exactly one reason."
        )
    return BrowserObservation(
        attempt=integer_value(
            item.get("attempt"),
            f"{where}.attempt",
            minimum=1,
            maximum=3,
        ),
        observed_at=timestamp(item.get("observed_at"), f"{where}.observed_at"),
        observer_id=observer_id,
        provenance=provenance,
        platform=string_value(
            item.get("platform"),
            f"{where}.platform",
            maximum=100,
        ),
        browser=browser,
        command=command_argv(item.get("command"), f"{where}.command"),
        flows_passed=string_tuple(
            item.get("flows_passed"),
            f"{where}.flows_passed",
        ),
        states_passed=string_tuple(
            item.get("states_passed"),
            f"{where}.states_passed",
        ),
        devices_passed=string_tuple(
            item.get("devices_passed"),
            f"{where}.devices_passed",
        ),
        viewports=string_tuple(
            item.get("viewports"),
            f"{where}.viewports",
        ),
        keyboard=boolean_value(item.get("keyboard"), f"{where}.keyboard"),
        focus_order=boolean_value(
            item.get("focus_order"),
            f"{where}.focus_order",
        ),
        readability=boolean_value(
            item.get("readability"),
            f"{where}.readability",
        ),
        contrast=boolean_value(item.get("contrast"), f"{where}.contrast"),
        information_structure=boolean_value(
            item.get("information_structure"),
            f"{where}.information_structure",
        ),
        efficiency=boolean_value(item.get("efficiency"), f"{where}.efficiency"),
        offline=boolean_value(item.get("offline"), f"{where}.offline"),
        recovery=boolean_value(item.get("recovery"), f"{where}.recovery"),
        screenshots=screenshots,
        trace=parse_artifact_reference(item.get("trace"), f"{where}.trace"),
        visual_regression=visual,
        visual_regression_reason=visual_reason,
        status=status,
        failures=string_tuple(item.get("failures"), f"{where}.failures"),
    )


def _valid_image_artifact(root: Path, reference: ArtifactReference) -> bool:
    if not verify_artifact(root, reference):
        return False
    path = root.joinpath(*PurePosixPath(reference.path).parts)
    try:
        content = path.read_bytes()
    except OSError:
        return False
    return path.suffix.casefold() == ".png" and _valid_png(content)


def _valid_png(content: bytes) -> bool:
    """Validate a bounded, complete PNG with positive dimensions and CRCs."""

    if len(content) < 45 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    width = 0
    height = 0
    channels = 0
    saw_header = False
    compressed = bytearray()
    saw_end = False
    phase = "header"
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        chunk_type = content[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > 1_000_000 or end > len(content):
            return False
        data = content[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", content[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return False
        if (
            len(chunk_type) != 4
            or not all(
                ord("A") <= value <= ord("Z") or ord("a") <= value <= ord("z")
                for value in chunk_type
            )
            or not ord("A") <= chunk_type[2] <= ord("Z")
        ):
            return False
        if not saw_header:
            if chunk_type != b"IHDR" or length != 13:
                return False
            width, height = struct.unpack(">II", data[:8])
            bit_depth, color_type, compression, filtering, interlace = data[8:]
            channels = {2: 3, 6: 4}.get(color_type, 0)
            if (
                not (0 < width <= 8_192 and 0 < height <= 8_192)
                or width * height > 16_000_000
                or bit_depth != 8
                or channels == 0
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                return False
            saw_header = True
            phase = "before-idat"
            offset = end
            continue
        elif chunk_type == b"IHDR":
            return False
        if chunk_type == b"IDAT":
            if phase not in {"before-idat", "idat"}:
                return False
            phase = "idat"
            compressed.extend(data)
            if len(compressed) > 1_000_000:
                return False
        elif chunk_type == b"IEND":
            if length != 0 or end != len(content):
                return False
            saw_end = True
            break
        elif chunk_type in _PNG_ANCILLARY_BEFORE_IDAT:
            if phase == "idat":
                if chunk_type not in _PNG_ANCILLARY_AFTER_IDAT:
                    return False
                phase = "after-idat"
            elif phase != "before-idat":
                return False
        elif saw_header:
            return False
        offset = end
    if not (saw_header and compressed and saw_end):
        return False
    expected_size = height * (1 + width * channels)
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(bytes(compressed), expected_size + 1)
        if decompressor.unconsumed_tail:
            return False
        pixels += decompressor.flush(max(1, expected_size + 1 - len(pixels)))
    except zlib.error:
        return False
    if (
        len(pixels) != expected_size
        or not decompressor.eof
        or decompressor.unused_data
    ):
        return False
    row_size = 1 + width * channels
    return all(pixels[offset] <= 4 for offset in range(0, len(pixels), row_size))


def _valid_browser_trace(
    root: Path,
    observation: BrowserObservation,
    candidate: CandidateIdentity,
) -> bool:
    try:
        payload = load_json_object(
            root.joinpath(*PurePosixPath(observation.trace.path).parts),
            "Browser execution trace",
            maximum_bytes=64 * 1024,
        )
    except ContractError:
        return False
    if set(payload) != {
        "schema_version",
        "candidate",
        "observation",
        "screenshots",
        "execution",
    }:
        return False
    expected_observation = {
        "observed_at": observation.observed_at,
        "observer_id": observation.observer_id,
        "provenance": observation.provenance,
        "platform": observation.platform,
        "browser": observation.browser,
        "command": list(observation.command),
        "flows_passed": list(observation.flows_passed),
        "states_passed": list(observation.states_passed),
        "devices_passed": list(observation.devices_passed),
        "viewports": list(observation.viewports),
        "keyboard": observation.keyboard,
        "focus_order": observation.focus_order,
        "readability": observation.readability,
        "contrast": observation.contrast,
        "information_structure": observation.information_structure,
        "efficiency": observation.efficiency,
        "offline": observation.offline,
        "recovery": observation.recovery,
        "visual_regression": observation.visual_regression,
        "visual_regression_reason": observation.visual_regression_reason,
        "status": observation.status.value,
        "failures": list(observation.failures),
    }
    execution = payload.get("execution")
    if not isinstance(execution, dict) or set(execution) != {
        "runner_id",
        "executable",
        "browser_version",
        "returncode",
        "duration_ms",
        "stdout_sha256",
        "stderr_sha256",
        "network_mode",
    }:
        return False
    runner_id = execution.get("runner_id")
    executable = execution.get("executable")
    browser_version = execution.get("browser_version")
    returncode = execution.get("returncode")
    duration_ms = execution.get("duration_ms")
    return (
        payload.get("schema_version") == "1.0"
        and payload.get("candidate") == candidate.to_dict()
        and payload.get("observation") == expected_observation
        and payload.get("screenshots")
        == [item.to_dict() for item in observation.screenshots]
        and isinstance(runner_id, str)
        and _RUNNER_ID.fullmatch(runner_id) is not None
        and isinstance(executable, str)
        and executable.casefold()
        in _BROWSER_EXECUTABLES.get(observation.browser, set())
        and observation.command[0].casefold() == executable.casefold()
        and isinstance(browser_version, str)
        and _BROWSER_VERSION.fullmatch(browser_version) is not None
        and isinstance(returncode, int)
        and not isinstance(returncode, bool)
        and -255 <= returncode <= 255
        and isinstance(duration_ms, int)
        and not isinstance(duration_ms, bool)
        and 0 <= duration_ms <= 300_000
        and isinstance(execution.get("stdout_sha256"), str)
        and re.fullmatch(r"[0-9A-F]{64}", execution["stdout_sha256"]) is not None
        and isinstance(execution.get("stderr_sha256"), str)
        and re.fullmatch(r"[0-9A-F]{64}", execution["stderr_sha256"]) is not None
        and execution.get("network_mode") == "offline"
        and (
            (observation.status is EvidenceStatus.PASS and returncode == 0)
            or (observation.status is EvidenceStatus.FAIL)
        )
    )
