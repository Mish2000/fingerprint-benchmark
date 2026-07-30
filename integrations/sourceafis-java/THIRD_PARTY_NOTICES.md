# Third-party notices — fpbench SourceAFIS bridge

`target/fpbench-sourceafis-bridge.jar` is a shaded ("fat") jar: it contains this
project's bridge classes **and** every dependency listed below, relocated into one
archive. Anyone who receives that jar receives all of them, so all of them are named
here.

The jar itself is not committed to this repository — it is built from source by
`./mvnw --batch-mode clean test package`, and its SHA-256 is recorded in the
environment fingerprint of every run that used it.

## The algorithm under test

| | |
|---|---|
| Project | SourceAFIS for Java |
| Maven coordinate | `com.machinezoo.sourceafis:sourceafis:3.18.1` |
| Version | 3.18.1 |
| License | Apache License 2.0 |
| Upstream | https://sourceafis.machinezoo.com/ |

The version is pinned exactly. No range, no `LATEST`, no `RELEASE`, no snapshot —
a benchmark whose dependency resolution can drift is a benchmark whose numbers can
drift.

## Everything bundled in the shaded jar

Enumerated from the shade plugin's own output, not from memory. License names are as
declared in each project's published POM.

| Artifact | Version | License |
|---|---|---|
| `com.machinezoo.sourceafis:sourceafis` | 3.18.1 | Apache-2.0 |
| `com.machinezoo.stagean:stagean` | 1.3.0 | Apache-2.0 |
| `com.machinezoo.closeablescope:closeablescope` | 1.0.1 | Apache-2.0 |
| `com.machinezoo.noexception:noexception` | 1.9.1 | Apache-2.0 |
| `com.machinezoo.fingerprintio:fingerprintio` | 1.3.1 | Apache-2.0 |
| `it.unimi.dsi:fastutil` | 8.5.12 | Apache License, Version 2.0 |
| `commons-io:commons-io` | 2.15.0 | Apache License, Version 2.0 (via `org.apache:apache` parent) |
| `com.google.code.gson:gson` | 2.10.1 | Apache-2.0 |
| `com.github.mhshams:jnbis` | 2.1.2 | The Apache Software License, Version 2.0 |
| `com.fasterxml.jackson.core:jackson-core` | 2.15.3 | The Apache Software License, Version 2.0 |
| `com.fasterxml.jackson.core:jackson-annotations` | 2.15.3 | The Apache Software License, Version 2.0 |
| `com.fasterxml.jackson.core:jackson-databind` | 2.15.3 | The Apache Software License, Version 2.0 |
| `com.fasterxml.jackson.dataformat:jackson-dataformat-cbor` | 2.15.3 | The Apache Software License, Version 2.0 |
| `org.slf4j:slf4j-api` | 2.0.9 | MIT License |

`slf4j-api` and `commons-io` declare their licences through parent POMs rather than
directly; SLF4J is distributed under the MIT licence and Commons IO under Apache-2.0
via the `org.apache:apache` parent.

Every dependency is Apache-2.0 or MIT. Both are permissive and compatible with each
other and with redistribution of the built jar; no copyleft or
source-availability obligation is introduced by any of them.

The `META-INF/LICENSE`, `META-INF/LICENSE.txt`, `META-INF/NOTICE` and
`META-INF/NOTICE.txt` entries from the bundled artifacts are preserved inside the
shaded jar.

## Direct dependency this project adds

`jackson-databind` is declared explicitly in `pom.xml` even though SourceAFIS already
brings it in transitively. The bridge parses JSON with it, and depending on it by
accident — through another project's dependency graph — would mean a SourceAFIS
upgrade could change our wire parsing without anyone deciding to.

## Build tooling (not redistributed)

Maven, the Maven Wrapper, the compiler, surefire and shade plugins, and JUnit 5 are
used to build and test the bridge. None of them ends up inside the shaded jar. JUnit
is `test`-scoped for exactly that reason.

## Not included

No NIST SD300 imagery, and no fingerprint image of any kind, is present in this
directory or in the built jar. See [data/README.md](../../data/README.md).
