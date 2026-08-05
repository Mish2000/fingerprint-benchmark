"""Re-derive the committed Stage 8B authority without torch or the weights."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.flx_models import FlxOutcome
from fpbench.flx.verify import verify_stage8b_evidence

pytestmark = pytest.mark.stage8b

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_CONFIG = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
POLICY_CONFIG = REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"


def test_the_committed_stage8b_evidence_rederives_without_a_runtime() -> None:
    verification = verify_stage8b_evidence(
        repository_root=REPOSITORY_ROOT,
        lock_config=LOCK_CONFIG,
        policy_config=POLICY_CONFIG,
    )

    assert verification.outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
    assert verification.gate_count == 15
    assert verification.evidence_files_verified == 10
    assert verification.opens_stage_8c is True


def test_verification_needs_neither_torch_nor_the_checkpoint() -> None:
    # The point of the split: verification that could only run where the
    # experiment ran would be the experiment agreeing with itself.
    import subprocess
    import sys

    probe = (
        "import sys;"
        "sys.modules['torch'] = None;"
        "sys.modules['torchvision'] = None;"
        "from pathlib import Path;"
        "from fpbench.flx.verify import verify_stage8b_evidence;"
        "root = Path.cwd();"
        "result = verify_stage8b_evidence("
        "repository_root=root,"
        "lock_config=root / 'configs/flx/flx_runtime_lock_v1.txt',"
        "policy_config=root / 'configs/flx/stage8b_flx_runtime_policy_v1.yaml');"
        "print(result.outcome.value)"
    )
    completed = subprocess.run(
        (sys.executable, "-c", probe),
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        timeout=300,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FLX_RAW_SCORE_EXECUTION_READY" in completed.stdout


def test_an_alternate_policy_is_refused_before_the_evidence_is_read(tmp_path: Path) -> None:
    alternate = tmp_path / "policy.yaml"
    alternate.write_text("not the frozen policy\n", encoding="utf-8")

    from fpbench.core.flx_errors import Stage8BFinalizationError

    with pytest.raises(Stage8BFinalizationError, match="exact repository-owned"):
        verify_stage8b_evidence(
            repository_root=REPOSITORY_ROOT,
            lock_config=LOCK_CONFIG,
            policy_config=alternate,
        )
