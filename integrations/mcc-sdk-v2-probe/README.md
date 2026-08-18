# MCC SDK v2.0 Stage 20A probe

This directory contains the smallest executable needed to qualify the official
University of Bologna MCC SDK v2.0. It is not a production adapter and it does
not contain or redistribute any vendor byte.

The probe is compiled outside the repository against `Sdk/MccSdk.dll`. It uses
only `SampleMinutiae/1_1.txt`, `1_2.txt`, and `2_1.txt` from the official archive,
constructs a new template for every side of every comparison, calls baseline MCC
without any parameter setter, and writes one JSON record to standard output.

It also inventories the assembly's exported API and observes two controlled
failure cases. Paths and vendor template contents are never written to the JSON.

Build and execution are orchestrated by
`python scripts/stage20a_mcc_sdk_preflight.py probe` on Windows with .NET
Framework 4.x installed. The DLL, compiled executable, sample data, and complete
probe output stay in the local fpbench third-party store.
