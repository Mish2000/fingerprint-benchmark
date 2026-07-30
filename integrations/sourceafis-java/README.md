# fpbench SourceAFIS bridge

A small Java program that reads two images, extracts two templates, matches them, and
prints one JSON document. Nothing else.

It exists because SourceAFIS is a Java library and the harness is Python. A subprocess
boundary is also the cheapest way to be certain the algorithm cannot see anything the
harness did not hand it — the request carries two paths and two resolutions, and no
pair id, subject, finger, stage, ground truth or threshold
([ADR 0010](../../docs/adr/0010-adapter-context-excludes-ground-truth.md),
[ADR 0015](../../docs/adr/0015-sourceafis-uses-stateless-java-bridge.md)).

## Build

```bash
./mvnw --batch-mode clean test package
```

Produces `target/fpbench-sourceafis-bridge.jar` — a fixed name, so the Python side
resolves an exact path and never has to glob for a jar. The jar is not committed; its
SHA-256 goes into the environment fingerprint of every run that uses it.

Requires JDK 17 or newer. 17 is the project's reference JVM and the only one the
regression score is pinned against.

## Commands

```bash
java -jar target/fpbench-sourceafis-bridge.jar version
java -jar target/fpbench-sourceafis-bridge.jar compare < request.json
```

`version` reports the SourceAFIS version **as reported by SourceAFIS at runtime**, not
a constant compiled in here. That is the point: it is what lets the Python side refuse
to run against a jar built from a different release.

```json
{
  "schema_version": "1",
  "bridge_version": "1",
  "bridge_protocol": "fpbench.sourceafis.bridge.v1",
  "sourceafis_version": "3.18.1",
  "java_version": "17.0.18",
  "java_vendor": "...",
  "java_vm_name": "...",
  "os_name": "...",
  "os_arch": "..."
}
```

### compare

Request on stdin:

```json
{
  "schema_version": "1",
  "request_id": "job_0123456789abcdef",
  "left":  {"path": "/absolute/path/left.png",  "dpi": 500},
  "right": {"path": "/absolute/path/right.png", "dpi": 2000}
}
```

Paths must be absolute. DPI must be finite and positive. Unknown fields are **rejected**
rather than ignored — a caller sending a field this bridge does not understand is
running a different protocol than it thinks.

Success:

```json
{
  "schema_version": "1", "request_id": "job_...", "status": "success",
  "score": 23.165, "sourceafis_version": "3.18.1", "bridge_version": "1",
  "extraction_count": 2,
  "timings_ms": {"left_input_read": 1.2, "left_template_extraction": 18.4,
                 "right_input_read": 1.1, "right_template_extraction": 17.9,
                 "matcher_initialization": 0.8, "matching": 0.3, "bridge_total": 40.2}
}
```

Failure — still exit code 0, because an unreadable or undecodable image is a *result*:

```json
{
  "schema_version": "1", "request_id": "job_...", "status": "failure",
  "code": "image_decode_failed", "stage": "left_extraction", "side": "left",
  "message": "Input image could not be decoded",
  "exception_type": "IllegalArgumentException",
  "sourceafis_version": "3.18.1", "bridge_version": "1",
  "timings_ms": {"left_input_read": 1.0, "bridge_total": 1.8}
}
```

Failure codes: `input_read_failed`, `image_decode_failed`, `unsupported_resolution`,
`template_extraction_failed`, `matching_failed`.

Messages are fixed strings and never contain a path, a filename or anything derived
from the image, because a failure document travels into stored results and from there
into reports.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | A document was produced. Includes an expected comparison failure. |
| 64 | The request was unusable — malformed JSON, unknown field, relative path, bad DPI. A caller bug. |
| 70 | Something in this program went wrong. Our bug. |

stdout carries exactly one JSON document and nothing else; diagnostics go to stderr.
SLF4J prints a "no providers were found" notice to stderr on every run, which is
harmless and ignored.

## Guarantees the tests enforce

* **Both sides are extracted independently**, even when the two paths are identical —
  which is what a SELF comparison looks like. `extraction_count` is reported so the
  caller can verify rather than trust, and a Java test counts the calls through an
  injected pipeline.
* **DPI is explicit.** SourceAFIS ignores the resolution a PNG header claims, which is
  exactly what this project needs: SD300C files declare 5080 ppi and are genuinely
  2000 ([ADR 0004](../../docs/adr/0004-sd300c-effective-ppi.md),
  [ADR 0016](../../docs/adr/0016-sourceafis-receives-explicit-effective-dpi.md)).
* **Left is the probe, right is the candidate.** Fixed. Never reversed, averaged, or
  maximised over both directions.
* **No threshold, no decision.** The score is SourceAFIS's own number
  ([ADR 0003](../../docs/adr/0003-decision-outside-adapter.md)).
* **No template is serialised, cached or persisted.**

## Layout

```
pom.xml                     dependencies, all pinned
mvnw, mvnw.cmd, .mvn/       Maven Wrapper (script-only; no jar committed)
THIRD_PARTY_NOTICES.md      everything bundled in the shaded jar
src/main/java/...
  BridgeMain                argument handling, exit codes, one document out
  BridgeVersion             identity; SourceAFIS version read at runtime
  CompareRequest            strict wire format and validation
  CompareResponse           the one document, two shapes
  BridgeFailure             expected-failure codes and stages
  SourceAfisComparisonService   read, extract, extract, match
src/test/java/...           unit tests, including the extraction-count spy
```

## Licensing

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). SourceAFIS is Apache-2.0;
everything bundled is Apache-2.0 or MIT.
