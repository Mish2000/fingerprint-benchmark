# FingerCell qualification bridge (Stage 13A)

The smallest program that can answer Stage 13A's runtime questions. It is **not**
an adapter: it produces no ResultSet, applies no threshold, makes no decision and
caches no template. Stage 13B builds the production integration, and only if
Stage 13A passes.

## Building does not start the trial

This is the point of the directory. `make` compiles and links, and stops.

There is deliberately no `check` target, no smoke test, no post-build execution
and nothing that loads a vendor module. The FingerCell trial runs 30 days from an
explicit activation, and a route that fails to compile should cost none of them
(docs/adr/0115).

```bash
make FPBENCH_FINGERCELL_SDK=/path/to/FingerCell_3_3_SDK
```

The SDK lives in the local artifact store, outside this repository. No vendor
byte is ever copied in here, and `build/` is ignored.

## What it links against

Not invented — exactly what the delivered tutorial build files name for the
official 1:1 route:

```
Tutorials/FingerCell/CPP/FCVerifyFingerCPP/Makefile
    LDLIBS ?= -lFingerCell -lNMedia -lNCore -lNLicensing
```

The built binary records the same four as its dynamic dependencies. The general
biometrics module that carries the vendor's other fingerprint engine is absent
from both, which is what the contamination claim rests on — with no vendor module
inspected to establish it (docs/adr/0114, docs/adr/0120).

## Subcommands

Each runs only when named. Output is `key=value` lines on stdout; errors go to
stderr with a non-zero exit status, and a failure is never reported as a score.

| Command | What it does |
|---------|--------------|
| `settings <trial>` | construct the engine and report every property it exposes, before anything is set |
| `extract <trial> <image> <out>` | one image → one fresh template at an effective 500 PPI |
| `match <trial> <ref> <cand>` | two templates → one native integer |
| `pair <trial> <left> <right>` | both orientations, each side extracted freshly |
| `self <trial> <image>` | two independent extractions of one image → one comparison |

`<trial>` is `0` or `1`. Trial mode is passed in rather than read from the
delivered flag file, so starting the clock is always something the caller asked
for by name.

## The rules it encodes

- **`pair.left → reference`, `pair.right → candidate`**, taken from the words the
  delivered header itself uses (docs/adr/0119). Both orientations are produced
  for observation; nothing averages, maximises or selects between them.
- **500 PPI is made true before extraction**, by setting the image's resolution
  metadata. Pixels are never touched — a rescale would be fpbench choosing a
  preprocessing step.
- **SELF is two loads and two extractions.** An engine that noticed both sides
  were the same object could return a constant, and that constant would describe
  this bridge rather than the algorithm.
- **Settings are read before they are set** (docs/adr/0118), through the SDK's own
  property capture rather than a list written in advance.
- **The licence is obtained for the `FingerCell` component by name**, because the
  benchmark already runs a different product from this vendor on the same host.

## Build state

Built and linked; **never executed**. The binary is pinned into the Stage 13A
inspection record by source fingerprint and binary digest, so a qualification run
can be bound to the exact build that produced it and cannot outlive an edit.
