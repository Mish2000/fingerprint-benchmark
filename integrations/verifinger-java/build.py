"""Build the fpbench VeriFinger bridge jar.

Not Maven, and the reason is worth stating. The bridge compiles against
Neurotechnology's own jars, which are licence-restricted bytes that live in a
local artifact store and may never enter this repository. A ``pom.xml`` could
only reach them through ``<scope>system</scope>`` and a
``<systemPath>``, which is a machine path in a committed file — precisely what
this project refuses to publish (spec sections 38 and 39).

So the build is forty lines of ``javac`` and ``jar``, and it resolves the
classpath the same way everything else on this route does: through
:mod:`fpbench.experiments.verifinger_runtime_manifest`, from the installation prepared out of the
pinned archive.

**The jar holds our bytes only.** Nothing is shaded in. The Neurotechnology jars
stay on the classpath at run time, where every one of them is pinned by digest,
rather than being copied into an artefact this project would then be
redistributing.

Run it with::

    python integrations/verifinger-java/build.py

The output is ``integrations/verifinger-java/target/fpbench-verifinger-bridge.jar``,
which is gitignored — like the SourceAFIS bridge, it is built on the machine
that runs it and identified by its SHA-256 rather than by being committed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = REPOSITORY_ROOT / "integrations" / "verifinger-java"
SOURCE = (
    INTEGRATION_ROOT
    / "src"
    / "main"
    / "java"
    / "org"
    / "fpbench"
    / "verifingerbridge"
    / "VeriFingerBridge.java"
)
TARGET = INTEGRATION_ROOT / "target"
CLASSES = TARGET / "classes"
JAR_NAME = "fpbench-verifinger-bridge.jar"
MAIN_CLASS = "org.fpbench.verifingerbridge.VeriFingerBridge"

#: Variables that inject JVM flags behind our back, removed for the same reason
#: the SourceAFIS bridge removes them.
_JVM_ENV_OVERRIDES = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")


def _tool(name: str) -> str:
    """``javac`` or ``jar``, from ``JAVA_HOME`` first and then from ``PATH``."""
    home = os.environ.get("JAVA_HOME", "").strip()
    if home:
        for suffix in ("", ".exe"):
            candidate = Path(home) / "bin" / (name + suffix)
            if candidate.is_file():
                return str(candidate)
    located = shutil.which(name)
    if located is None:
        raise SystemExit(
            f"{name} was not found on JAVA_HOME or PATH; this project pins "
            "openjdk=17 in environment.yml"
        )
    return located


def _environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in _JVM_ENV_OVERRIDES
    }


def build(*, repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Compile and package the bridge, and return the jar's path.

    Raises:
        SystemExit: the toolchain is missing, the pinned installation is not
            available, or the compilation failed. Every one of them is an
            operator problem with a clear next step, not a stack trace.
    """
    from fpbench.experiments.stage11a_qualification import prepare_installation
    from fpbench.adapters.verifinger_java.runtime import classpath_entries

    if not SOURCE.is_file():
        raise SystemExit(f"the bridge source is missing: {SOURCE.name}")

    installation = prepare_installation(repository_root=Path(repository_root))
    classpath = os.pathsep.join(str(item) for item in classpath_entries(installation))

    if CLASSES.exists():
        shutil.rmtree(CLASSES)
    CLASSES.mkdir(parents=True)

    compiled = subprocess.run(
        (
            _tool("javac"),
            "-encoding",
            "UTF-8",
            "-Xlint:all",
            "-cp",
            classpath,
            "-d",
            str(CLASSES),
            str(SOURCE),
        ),
        check=False,
        capture_output=True,
        text=True,
        env=_environment(),
    )
    if compiled.returncode != 0:
        raise SystemExit(
            "the VeriFinger bridge did not compile against the pinned "
            f"bindings:\n{compiled.stderr.strip()}"
        )
    if compiled.stderr.strip():
        print(compiled.stderr.strip(), file=sys.stderr)

    jar = TARGET / JAR_NAME
    if jar.exists():
        jar.unlink()
    packaged = subprocess.run(
        (
            _tool("jar"),
            "--create",
            "--file",
            str(jar),
            "--main-class",
            MAIN_CLASS,
            "-C",
            str(CLASSES),
            ".",
        ),
        check=False,
        capture_output=True,
        text=True,
        env=_environment(),
    )
    if packaged.returncode != 0:
        raise SystemExit(f"packaging failed:\n{packaged.stderr.strip()}")
    return jar


def main() -> int:
    import hashlib

    jar = build()
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    print(f"built {jar.relative_to(REPOSITORY_ROOT).as_posix()}")
    print(f"sha256 {digest}")
    print(f"size   {jar.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
