# Stage 20B MCC SDK v2.0 production bridge

The process that stands between fpbench and the official University of Bologna
MCC SDK v2.0. It contains no vendor byte and redistributes nothing.

## What it does

One process per comparison, and only these three calls:

```text
CreateMccTemplate(left.width, left.height, 500, left.minutiae)
CreateMccTemplate(right.width, right.height, 500, right.minutiae)
MatchMccTemplates(leftTemplate, rightTemplate)
```

It then prints one tab-separated line:

```text
status  score  template_left_us  template_right_us  match_us  left_n  right_n  detail
```

`identity` is the other command. It reports the loaded assembly and every one of
the SDK's optimal enroll and match parameters, so that `validate_environment()`
can compare them to the values Stage 20A recorded before a run starts. Nothing
sets a parameter; the bridge only reads them back.

## What it deliberately does not contain

No parameter setter, no threshold, no score transform, no filtering, no top-N, no
sorting, no deduplication, no rotation search, no clamping of an out-of-range
score, no cache, and no state between invocations. Every biometric decision
belongs to the SDK and every benchmark decision belongs to fpbench.

A score of `0.0` is a successful similarity and is never a failure sentinel. An
exception is never turned into a score, in either direction.

## Wire format

The payload is the SDK's own documented minutiae text format (manual, Appendix A)
twice over, so a payload can be read against Bologna's own `SampleMinutiae`
examples:

```text
FPBENCH-MCC-BRIDGE-1
LEFT <width> <height> <resolution> <n>
<x> <y> <direction>
...
RIGHT <width> <height> <resolution> <n>
<x> <y> <direction>
...
```

Directions are written in Python's shortest round-tripping form and read with
`Double.TryParse` under the invariant culture, so the angle the matcher sees is
bit-for-bit the angle the adapter computed.

Anything unexpected in a payload is a `BRIDGE_FAILURE`, never a guess.

## Building it

```bash
python scripts/stage20b_gate_a.py --build
```

Compiles `Program.cs` with the .NET Framework 4.x `csc` that ships with Windows,
against a verified copy of `Sdk/MccSdk.dll` from the official archive, into the
local third-party store. The assembly is copied next to the executable because
.NET resolves a dependency from the application's own directory — this route must
never load an `MccSdk.dll` that happens to be elsewhere on the machine — and its
SHA-256 is checked both before and after the copy.

The DLL, the archive, the sample minutiae and the compiled bridge all stay in the
local artifact store. Stage 20A recorded
`official_artifact_cannot_be_redistributed_by_this_repository`, and that has not
changed.

## Running it under WSL

The bridge is executed by its Linux path — that is how WSL interop starts a
Windows process — but it reads its payload *as* a Windows process, so the payload
argument is translated by `fpbench.adapters.mcc.interop`. The executable's own
path is not translated. A workspace Windows cannot see is refused rather than
guessed at.
