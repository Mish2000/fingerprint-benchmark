"""The one thing that has to cross the Linux/Windows boundary: a file name.

Stage 20B runs on two operating systems at once, on purpose. The extractor must
be Algorithm 2's certified Linux build — compiling a second MINDTCT for Windows
would quietly make "the same extractor" untrue — and the matcher is a .NET
Framework assembly that runs on Windows. WSL interop joins them: a Linux process
executes ``/mnt/c/…/FpbenchMccBridge.exe`` and Windows runs it.

What interop does **not** do is rewrite the arguments. The bridge is handed a
payload path, and a Windows process asked to open ``/mnt/c/x/y`` looks for a
directory called ``mnt`` on the current drive and does not find one. So this
module translates that one string, and only that one string:

.. code-block:: text

    /mnt/c/users/x/payload.txt   ->   C:\\users\\x\\payload.txt

The executable's own path is *not* translated: Linux needs the Linux name to
start the process at all.

**A path that cannot cross is refused, never guessed.** If the job's working
directory is somewhere Windows cannot see — a native ext4 home, say — there is no
correct translation, and inventing one would produce a bridge failure per
comparison with a misleading cause. The route's real constraint is that the
workspace lives on a Windows-visible mount, and this is where that is said.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = ["InteropPathUnreachable", "WSL_MOUNT_ROOT", "windows_path"]

#: Where WSL puts the Windows drives. The default, and the only layout this route
#: supports; a machine with ``automount.root`` set elsewhere is a different
#: environment and should say so rather than be guessed at.
WSL_MOUNT_ROOT = "/mnt"


class InteropPathUnreachable(ValueError):
    """A file the Windows bridge is meant to read is not on a Windows drive."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"{path} is not under {WSL_MOUNT_ROOT}/<drive>, so the Windows MCC "
            "bridge cannot open it; this route's workspace must live on a "
            "Windows-visible mount"
        )
        self.path = Path(path)


def windows_path(path: Path) -> str:
    """``path`` as the Windows bridge will see it.

    A no-op when this process is already on Windows — there the bridge and the
    caller share a filesystem and a path is a path.

    Raises:
        InteropPathUnreachable: on Linux, when the path is not under a mounted
            Windows drive.
    """
    if sys.platform == "win32":
        return str(Path(path))

    # Read as POSIX explicitly rather than through ``Path``: the rule being
    # applied is about the *Linux* side of the boundary, and ``Path`` on a
    # Windows host would parse the same text with the other separator, so a test
    # there would be checking a different parser from the one production runs.
    parts = PurePosixPath(os.fspath(path)).parts
    if len(parts) < 3 or parts[0] != "/" or f"/{parts[1]}" != WSL_MOUNT_ROOT:
        raise InteropPathUnreachable(path)
    drive = parts[2]
    if len(drive) != 1 or not drive.isalpha():
        raise InteropPathUnreachable(path)
    return str(PureWindowsPath(f"{drive.upper()}:\\", *parts[3:]))
