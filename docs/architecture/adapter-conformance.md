# Adapter conformance

The contract in docs/adr/0002 is worth something only if satisfying it is
checkable. `fpbench.adapters.conformance` is where the checks live, as ordinary
product code: a case in, a report out, no pytest anywhere near it.

That matters for two reasons. An adapter that needs two executables materialised
into a runtime bundle before it can run cannot be built by a registry-parametrised
fixture. And an adapter author wants to find out what is missing *before* wiring
up an experiment, from a list of findings rather than from the first assertion
that happened to fail.

## Running it

```python
from fpbench.adapters.conformance import AdapterConformanceCase, run_adapter_conformance

case = AdapterConformanceCase(
    adapter_id="nbis_mindtct_bozorth3",
    factory=NbisAdapter.from_config,
    ready_config={...},              # everything present
    unavailable_config={...},        # one dependency missing
    left_image=..., right_image=...,
    expected_score_direction=ScoreDirection.HIGHER_IS_BETTER,
)

report = run_adapter_conformance(
    case,
    working_directory=work, artifact_directory=artifacts, sandbox_root=root,
)
report.require_clean()
```

`sandbox_root` must contain the two job directories **and** the input images:
anything created underneath it that is not inside one of the two job directories
is a stray write, and that is how the check finds one.

`run_adapter_conformance` never raises for a non-conformant adapter. The findings
are the answer; `require_clean()` is what turns them into a failure when you want
one.

The three calls use separate `forward-1`, `forward-2` and `reverse-1`
subdirectories. An adapter may therefore publish immutable artifacts under the
same fixed names on every call. Exceptions, input mutation, stray writes and
artifact integrity are rechecked after each invocation.

## What it checks

**Identity**

- the factory returns a `FingerprintAlgorithmAdapter`;
- `algorithm_id` and `adapter_id` are usable as directory names and dict keys;
- versions and display name are non-empty;
- the declared contract version is one this harness drives;
- the descriptor is the same object twice running — a descriptor rebuilt per
  access would change the algorithm fingerprint mid-run;
- the registry resolves `adapter_id` to this adapter (skipped, explicitly, for a
  fixture that is deliberately unregistered);
- the declared score direction is the expected one;
- if the route declares a `probe_side`, it is `left`.

**Environment**

- READY when the dependencies are present, with an implementation version;
- UNAVAILABLE when one is missing;
- a missing dependency is a *report*, never an exception. One fault of the run,
  not six thousand identical per-pair failures.

**The result**

- `compare` returns a `RawMatchResult`;
- its score direction matches the descriptor's;
- a success carries a finite score and no failure; a failure carries neither;
- metadata is string to string;
- metadata carries no threshold, decision, ground truth, protocol stage, subject,
  finger or pair id — an adapter that recorded one would have had to be given it
  (docs/adr/0003, docs/adr/0010);
- metadata holds no absolute path: a result that embeds one machine's layout is
  not portable evidence;
- every artefact reference is relative, contained, hashes to what it claims, and
  resolves without following a symlink or accepting a multi-link file.

**Isolation**

- the input files are byte-identical afterwards;
- nothing was written outside `working_directory` and `artifact_directory`;
- a deterministic adapter repeats itself;
- reversing the two sides is answered as a separate call.

## On the reversed-sides check

`compare(left, right)` fixes left as the probe and right as the candidate. A
symmetric algorithm may legitimately return the same score both ways, so
equality proves nothing and is not failed. The generic check proves only that
both orders were invoked and answered in kind. When direction affects an
adapter, its case supplies `directional_golden(forward, reverse)` to prove the
expected asymmetric behavior; a generic suite cannot detect silent sorting.

What an adapter may **not** do is decide for itself: no automatic swap, no mean
of the two directions, no maximum of the two. Asymmetry, if it is ever worth
measuring, is a separate experiment with its own run identity, not a quiet choice
inside a wrapper.

## Making sure the checks can fail

A check that never fires is not a check.
`tests/contract/test_adapter_conformance_suite.py` therefore includes adapters
that write outside their directories, record a forbidden decision, raise from
`compare`, return a symlink artifact and mutate an input only on the second call.
It also includes a conformant adapter that publishes a fixed artifact name.

## Where it runs

| suite | adapters |
|---|---|
| `tests/contract/test_adapter_contract.py` | every registered adapter, parametrised |
| `tests/contract/test_adapter_conformance_suite.py` | dummy matcher, two-stage fixture, SourceAFIS |
| `.github/workflows/adapter-contract.yml` | everything that needs no JVM and no dataset |
| `.github/workflows/sourceafis-adapter.yml` | SourceAFIS, with a real JVM |

A new adapter joins the first by being registered, and the second by being given
a case.
