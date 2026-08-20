"""Handing an adapter two images without handing it the answer.

:class:`~fpbench.core.execution_models.PreparedImage` promises, in as many
words, that it carries "nothing that would let an adapter infer what the
comparison is for. There is no subject, no finger, no impression and no pair
here." Two of its fields broke that promise.

``image_id`` is composed, for SD300, as ``<release>_<subject>_<impression>_<finger>``
(``fpbench.datasets.sd300.catalog``). An adapter handed two of those can read
the subject out of each and answer *mated or not* before it has looked at a
single ridge. ``local_path`` carries the same information a second time, in the
filename the dataset publisher chose.

Nothing was exploiting it. That is not the point: a benchmark whose inputs
contain the ground truth cannot demonstrate that a score was earned, and the
demonstration is the whole product.

**What this module does.** Every image gets a per-run alias — sixteen hex
characters over a secret drawn fresh for this run — and the bytes are placed at
a path named after the alias. The alias is stable within a run, so the same
image is the same alias on both sides of a pair and across every job, and an
adapter that legitimately caches by input identity still can. It is unrelated
across runs, so two runs' logs cannot be joined on it.

**What this module does not do.** It is not a defence against a hostile adapter.
Adapters run in this process; one that wanted the mapping could read it out of
memory. What it removes is *inference from the inputs* — the thing an ordinary,
well-meaning adapter could do by accident, and the thing a reader of the results
has no way to rule out while the ids are readable. After this, an adapter that
knows which pairs are mated had to work for it, and that is a different claim
from "it might just have read the filename".

**Why a copy, and not a hard link.** A link would have been free — the same
inode under another name, so the digest checks the NBIS input path performs
would see the preparer's exact bytes at no I/O cost. The prepared-image store
forbids it, and is right to: it requires a canonical artefact to be *the only
name for its bytes*, because a second name is a second way to rewrite a blob
that is supposed to be immutable. Blinding does not get to weaken an integrity
control to save a copy.

The copy is made per job and removed with the job (:meth:`RunBlinding.discard`),
which also means a run holds no leftovers (spec section 32) and that an artefact
replaced mid-run is still read fresh — so
:class:`~fpbench.core.errors.PreparedImageDriftError` still fires (docs/adr/0033)
rather than being masked by a stale link.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import secrets
import shutil
from pathlib import Path

from fpbench.core.execution_models import PreparedImage
from fpbench.core.identifiers import ImageId

__all__ = ["RunBlinding", "BLIND_INPUT_DIRECTORY"]

#: Where a job's blinded inputs live, relative to the job's working directory.
BLIND_INPUT_DIRECTORY = "_input"

#: How many hex characters of the HMAC become the alias. Sixty-four bits is far
#: more than the 3,000 images a run distinguishes, and short enough to keep the
#: path within Windows' limit in the nested workspace layout.
_ALIAS_HEX = 16


class RunBlinding:
    """Per-run opaque aliases, and the blinded input paths that go with them.

    One instance per run. The secret lives only in memory: it is never written
    to a result, an artefact or the workspace, so nothing published can be used
    to reverse the aliases afterwards.
    """

    __slots__ = ("_secret", "_aliases", "_originals")

    def __init__(self, *, secret: bytes | None = None) -> None:
        # A caller may pin the secret to make a test's aliases reproducible.
        # Production never does: a fresh secret is what keeps two runs'
        # aliases unrelatable.
        self._secret = bytes(secret) if secret is not None else secrets.token_bytes(32)
        self._aliases: dict[str, ImageId] = {}
        self._originals: dict[str, str] = {}

    def alias_for(self, image_id: str) -> ImageId:
        """The opaque id this run uses for ``image_id``.

        Stable for the lifetime of the run, and computed rather than counted, so
        that the *order* images were first seen in leaks nothing either. A
        counter would have made the first image of the first pair ``img_1``.
        """
        key = str(image_id)
        alias = self._aliases.get(key)
        if alias is None:
            digest = hmac.new(self._secret, key.encode("utf-8"), hashlib.sha256)
            alias = ImageId(f"img_{digest.hexdigest()[:_ALIAS_HEX]}")
            self._aliases[key] = alias
            self._originals[str(alias)] = key
        return alias

    def original_of(self, alias: str) -> str | None:
        """The id an alias was minted for, or ``None`` if this run never saw it.

        For the harness, never for an adapter. A test that scripts a score per
        pair of images has to name those images somehow, and this is how it does
        so without the adapter under test being handed anything a real one would
        not get.
        """
        return self._originals.get(str(alias))

    def blind(self, prepared: PreparedImage, working_directory: Path) -> PreparedImage:
        """``prepared`` with an opaque id, and its bytes under an opaque name.

        Every other field is carried over untouched. The digests, the
        resolution and the preparation-set identities are provenance an adapter
        is entitled to and none of them names a subject.

        A source file that is not there is *not* an error here: the blinded path
        is returned pointing at nothing, so the adapter reports the missing
        input exactly as it did before, under its own failure code.
        """
        alias = self.alias_for(str(prepared.image_id))
        source = Path(prepared.local_path)
        directory = Path(working_directory) / BLIND_INPUT_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{alias}{source.suffix}"

        if source.is_file():
            _materialise(source, target)

        return dataclasses.replace(
            prepared, image_id=alias, local_path=target.resolve()
        )


    @staticmethod
    def discard(working_directory: Path | None) -> None:
        """Remove a job's blinded inputs once the adapter has finished with them.

        The links are intermediates of one comparison and leave with it, so a
        finished run holds none (spec section 32). Failure to remove one is not
        a fact about the pair and never becomes a recorded failure: the job
        directory is disposable, and the next thing to notice will be the
        housekeeping that empties ``work/``.
        """
        if working_directory is None:
            return
        directory = Path(working_directory) / BLIND_INPUT_DIRECTORY
        if not directory.is_dir():
            return
        for entry in directory.iterdir():
            try:
                entry.unlink()
            except OSError:  # pragma: no cover - a locked file is left behind
                pass
        try:
            directory.rmdir()
        except OSError:  # pragma: no cover - a non-empty directory stays
            pass


def _materialise(source: Path, target: Path) -> None:
    """Put ``source``'s current bytes at ``target``, freshly.

    A copy rather than a hard link, because a canonical artefact must remain the
    only name for its bytes — see the module docstring. ``shutil.copyfile``
    copies content and not mode, so the copy is writable even where the artefact
    is read-only, and :meth:`RunBlinding.discard` can remove it afterwards.

    Re-created rather than reused: two sides of a SELF pair resolve to one
    target, and a job must see the artefact as it is *now* rather than as it was
    when some earlier job staged it.
    """
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    shutil.copyfile(source, target)
