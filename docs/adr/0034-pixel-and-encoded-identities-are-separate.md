# 0034 — Pixel identity and encoded-file identity are both retained

*Status: Accepted — 2026-07-31, stage 6A*

## Context

Two different questions get asked about a canonical artefact, and one digest
cannot answer both.

*Is this the same image?* — a question about the grayscale raster. Re-encoding
the same pixels at a different compression level, or with a different zlib
build, produces a different file and the same image.

*Is this the same file the adapter opened?* — a question about the bytes. Two
files with identical pixels are still two files, and a matcher that reads a
container is affected by the container.

Storing only the file digest would make an innocuous re-encode look like new
data. Storing only the raster digest would make a re-encode invisible, including
one that changed metadata the profile forbids.

## Decision

Every canonical artefact carries **two** digests, and both are load-bearing.

`pixel_sha256` is the scientific identity of the raster:

```
sha256(b"fpbench.gray8.v1\0"
       + width.to_bytes(8, "big")
       + height.to_bytes(8, "big")
       + row_major_gray8_bytes)
```

The magic prefix stops a bare byte string being mistaken for a raster, and the
dimensions are inside the digest so a 4x6 raster and a 6x4 one holding the same
bytes are not the same image.

`encoded_sha256` is the digest of the PNG file. It is the content address the
artefact is stored under and the value a result records as `prepared_sha256`.

Both are inside `entry_hash`, and therefore inside the set fingerprint. Changing
only the compression moves the encoded digest and not the pixel one; changing
one pixel moves both.

## Consequences

The SD300A control invariant becomes expressible: `source_pixel_sha256 ==
output_pixel_sha256` for every 500 ppi image, *while* the encoded digests differ
because the identity path still re-encodes through this project's encoder rather
than copying NIST's file. Copying would be faster and would leave one release
carrying the delivery's PNG encoding while the other two carried ours — so a
difference between releases could be a difference in the container.

Verification can also distinguish the two failure modes it will actually meet: a
corrupted file (encoded digest moves, decode fails or raster moves) from a
re-encoded one (encoded digest moves, raster does not).

## Alternatives considered

**One digest over the file.** Simpler, and unable to state the control
invariant at all.

**One digest over the raster.** Would let a canonical PNG acquire a `tEXt` chunk
naming a subject id without anything noticing.
