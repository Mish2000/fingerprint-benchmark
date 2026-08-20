# Convenience targets. Everything here is a one-liner someone would otherwise have to
# remember; nothing here is load-bearing logic.

MVNW := ./integrations/sourceafis-java/mvnw
POM := integrations/sourceafis-java/pom.xml
BRIDGE_JAR := integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar

.PHONY: help test test-all full-run adapter-contract \
        nbis-inspect nbis-seal nbis-fetch nbis-build nbis-certify nbis-verify \
        nbis-contract nbis-upstream nbis-canonical500-preflight \
        stage7d-contract stage7d-workspace stage8a-contract stage8a-workspace stage8a-status \
        stage8b-contract stage8b-workspace stage8b-status \
        stage8c-contract stage8c-evidence stage8c-workspace stage8c-verify \
        stage8d-contract stage8d-evidence stage8d-qualify \
        sourceafis-build sourceafis-java-test sourceafis-python-test \
        sourceafis-test sourceafis-sd300-smoke \
        research-prepare research-execute research-status research-finalize \
        decisions-test decisions-prepare decisions-derive decisions-status \
        decisions-finalize \
        metrics-test metrics-prepare metrics-derive metrics-status \
        metrics-finalize metrics-show \
        imaging-test imaging-fixtures canonical-prepare canonical-materialize \
        canonical-status canonical-finalize \
        canonical-run-prepare canonical-run-execute canonical-run-status \
        canonical-run-finalize \
        stage15a-contract stage15a-evidence stage15a-artifacts stage15a-acquire \
        stage15a-runtime stage15a-runtime-verify stage15a-route stage15a-qualify \
        stage15a-preflight stage15a-status stage15a-integrity stage15a-verify \
        stage15a-documents stage15a-publish \
        stage16a-contract stage16a-evidence stage16a-acquire stage16a-artifacts \
        stage16a-route stage16a-verify stage16a-documents stage16a-publish \
        stage17a-contract stage17a-evidence stage17a-acquire stage17a-artifacts \
        stage17a-score stage17a-verify stage17a-documents stage17a-publish \
        stage20b-contract stage20b-evidence stage20b-build stage20b-gate-a \
        stage20b-gate-b stage20b-environment stage20b-run stage20b-publish

help:
	@echo "test                    unit + integration, no dataset, no Java, no full run"
	@echo "test-all                everything available on this machine"
	@echo "publication-hygiene     what evidence, workbooks and the README claim about themselves"
	@echo "full-run                the 6,000-job dummy protocol (minutes)"
	@echo "adapter-contract        what a new algorithm must satisfy (no dataset, no JVM)"
	@echo "stage7d-contract        the comparison methodology (no dataset, no algorithm)"
	@echo "stage7d-workspace       the comparison over the real 12,000 results"
	@echo "stage8a-contract        modern artifact qualification and selection rules (offline, no data)"
	@echo "stage8a-workspace       verify the committed Stage 8A evidence authority"
	@echo "stage8a-status          re-derive and print the Stage 8A outcome"
	@echo "stage8b-contract        the frozen flx protocol: identities, profiles, gates (no torch)"
	@echo "stage8b-workspace       verify the committed Stage 8B runtime qualification"
	@echo "stage8b-status          re-derive and print the Stage 8B outcome"
	@echo "stage8c-contract        the frozen Stage 8C protocol: identities, config, adapter, alignment (no torch)"
	@echo "stage8c-evidence        verify the committed Stage 8C raw-run evidence (no dataset, no runtime)"
	@echo "stage8d-contract        the generic calibration engine: rates, boundaries, ties, leakage (synthetic only)"
	@echo "stage8d-evidence        verify the committed Stage 8D calibration-infrastructure evidence"
	@echo "stage8d-qualify         re-run the synthetic qualification and print its fingerprint"
	@echo "stage8e-contract        the research-only third-party policy: purpose, decisions, artifacts, guard"
	@echo "stage8e-evidence        verify the committed Stage 8E research-only-policy evidence"
	@echo "stage8e-status          re-derive and print the Stage 8E audits and fingerprints"
	@echo "stage8e-guard           refuse if any third-party byte is tracked in this public repository"
	@echo "stage8e-documents       write the five derivable evidence documents (commit them, then publish)"
	@echo "stage8e-publish         write the marker too; refuses a dirty tree"
	@echo "stage9a-contract        the FLARE qualification: identity, artifacts, transform graph, score"
	@echo "stage9a-evidence        verify the committed Stage 9A FLARE artifact-qualification evidence"
	@echo "stage9a-artifacts       run the checks that need FLARE artifacts in the local store"
	@echo "stage9a-status          re-derive and print the Stage 9A outcome and its blockers"
	@echo "stage9a-guard           refuse if any FLARE byte is tracked in this public repository"
	@echo "stage9a-acquire         fetch the FLARE artifacts into the local store (local only, never CI)"
	@echo "stage9a-enroll          report the digest and size an unenrolled artifact would need frozen"
	@echo "stage9a-documents       write the nine derivable evidence documents (commit them, then publish)"
	@echo "stage9a-publish         write the marker too; refuses a dirty tree"
	@echo "stage10a-contract       the Algorithm 4 candidate preflight: gates, order, fail-fast, selection"
	@echo "stage10a-evidence       verify the committed Stage 10A candidate-preflight evidence"
	@echo "stage10a-artifacts      run the checks that need the pinned candidate source locally"
	@echo "stage10a-status         re-derive and print the gate matrix, the verdicts and the blockers"
	@echo "stage10a-guard          refuse if any candidate byte is tracked in this public repository"
	@echo "stage10a-documents      write the twenty derivable evidence documents (commit them, then publish)"
	@echo "stage10a-publish        write the marker too; refuses a dirty tree"
	@echo "stage10b-contract       the id3 Finger SDK preflight: ten gates, access, capacity, profiles, secrets"
	@echo "stage10b-evidence       verify the committed Stage 10B id3-preflight evidence"
	@echo "stage10b-artifacts      run the checks that need a delivered id3 SDK locally"
	@echo "stage10b-status         re-derive and print the gates, the verdict and the blockers"
	@echo "stage10b-guard          refuse if any id3 package, model or licence material is tracked here"
	@echo "stage10b-documents      write the thirteen derivable evidence documents (commit them, then publish)"
	@echo "stage10b-publish        write the marker too; refuses a dirty tree"
	@echo "stage11a-contract       the VeriFinger 2025.2 preflight: seventeen gates, provenance, raw score, secrets"
	@echo "stage11a-evidence       verify the committed Stage 11A VeriFinger-preflight evidence"
	@echo "stage11a-acquire        fetch the official VeriFinger artifacts (~4.8 GB) into the local store"
	@echo "stage11a-verify         report whether this machine holds the pinned artifacts"
	@echo "stage11a-artifacts      run the checks that need the pinned artifacts locally"
	@echo "stage11a-qualify-check  report the three preconditions for a local qualification run"
	@echo "stage11a-qualify        run the bounded local qualification (needs an activated trial)"
	@echo "stage11a-status         re-derive and print the gates, the verdict, blockers and actions"
	@echo "stage11a-guard          refuse if any Neurotechnology archive, model or licence material is tracked here"
	@echo "stage11a-documents      write the fifteen derivable evidence documents (commit them, then publish)"
	@echo "stage11a-publish        write the marker too; refuses a dirty tree"
	@echo "verifinger-build        build the Stage 11B production bridge jar from the pinned bindings"
	@echo "verifinger-runtime-verify  re-hash the seventeen pinned runtime components"
	@echo "stage11b-contract       the Stage 11B protocol: identity, wire format, failures, closure, config"
	@echo "stage11b-evidence       verify the committed Stage 11B canonical500 raw-run evidence"
	@echo "stage11b-artifacts      run the checks that need the pinned SDK and an activated licence"
	@echo "stage11b-smoke          the production adapter smoke on fixtures that are not SD300"
	@echo "stage11b-preflight      check every input the 6,000 run will read, and write nothing"
	@echo "stage11b-status         report where Stage 11B stands"
	@echo "stage11b-verify         re-derive and print the Stage 11B evidence-only verification"
	@echo "stage11b-documents      write the seven derivable evidence documents (commit them, then publish)"
	@echo "stage11b-publish        write the marker too"
	@echo "stage12a-contract       the Innovatrics IDKit preflight: ten gates, acquisition, single-finger raw score"
	@echo "stage12a-evidence       verify the committed Stage 12A IDKit-preflight evidence"
	@echo "stage12a-acquire        report every official route and the final acquisition state"
	@echo "stage12a-artifacts      run the checks that need a delivered IDKit package locally"
	@echo "stage12a-qualify-fake   drive the whole qualification harness against the fake SDK"
	@echo "stage12a-qualify        run the bounded local qualification (needs a delivered package)"
	@echo "stage12a-status         re-derive and print the gates, outcome and routing decision"
	@echo "stage12a-guard          refuse if any IDKit package or licence material is tracked here"
	@echo "stage12a-documents      write the eleven derivable evidence documents (commit them, then publish)"
	@echo "stage12a-publish        write the final marker too; refuses a dirty tree"
	@echo "stage13a-contract       the FingerCell 3.3 preflight: ten gates, ACTION_REQUIRED, raw 1:1 integer score"
	@echo "stage13a-evidence       verify the committed Stage 13A FingerCell-preflight evidence"
	@echo "stage13a-status         re-derive and print the gates, the outcome and what remains to be done"
	@echo "stage13a-acquire        report where the official trial archive stands in the local store"
	@echo "stage13a-declare        record an archive already in the store (ARCHIVE=<filename>)"
	@echo "stage13a-artifacts      run the checks that read the delivered FingerCell archive locally"
	@echo "stage13a-qualify-fake   drive the whole qualification harness against the fake SDK"
	@echo "stage13a-qualify        report the bounded local qualification record (needs the trial)"
	@echo "stage13a-guard          refuse if any FingerCell archive or licence material is tracked here"
	@echo "stage13a-contamination  prove no Stage 13A module reaches the same vendor's other algorithm"
	@echo "stage13a-documents      write the twelve derivable evidence documents (commit them, then publish)"
	@echo "stage13a-publish        write the final marker too; refuses while an action is outstanding"
	@echo "stage14a-contract       the Griaule preflight: four gates, five states, raw 1:1 score, route closure"
	@echo "stage14a-evidence       verify the committed Stage 14A Griaule-preflight evidence"
	@echo "stage14a-status         re-derive and print the gates, the outcome and what remains"
	@echo "stage14a-acquire        report every official route walked and where acquisition stands"
	@echo "stage14a-declare        record a delivered package already in the store (PACKAGE=... LOCATOR=... CHANNEL=...)"
	@echo "stage14a-guard          refuse if any Griaule package or licence material is tracked here"
	@echo "stage14a-artifacts      run the checks that need a delivered Griaule package locally"
	@echo "stage14a-documents      write the eight derivable evidence documents (commit them, then publish)"
	@echo "stage14a-publish        write the final marker too; refuses a non-final outcome"
	@echo "stage20a-contract       verify the mechanical MINDTCT-to-MCC representation contract"
	@echo "stage20a-evidence       verify the committed MCC SDK v2.0 preflight evidence"
	@echo "stage20a-acquire        fetch and pin the official BioLab MCC SDK v2.0 archive outside Git"
	@echo "stage20a-probe          compile and run the small C# qualification probe on SDK samples"
	@echo "stage20a-publish        derive the Stage 20A evidence and PASS marker"
	@echo "stage20a-verify         re-derive evidence hashes and the Stage 20A source fingerprint"
	@echo "stage20b-contract       verify the frozen MINDTCT-to-MCC production route rules"
	@echo "stage20b-evidence       verify the committed Stage 20B canonical raw evidence"
	@echo "stage20b-build          compile the production MCC bridge and record its manifest"
	@echo "stage20b-gate-a         reproduce Stage 20A's official-sample scores exactly"
	@echo "stage20b-gate-b         prove this route's MINDTCT is Algorithm 2's, byte for byte"
	@echo "stage20b-run            the 6,000 canonical comparisons under MINDTCT + MCC SDK v2.0"
	@echo "stage20b-publish        diagnostics, the eight evidence documents and the marker"
	@echo "stage15a-contract       the fingerprints-matching qualification: six gates, the route contract, the failure split"
	@echo "stage15a-evidence       verify the committed Stage 15A evidence"
	@echo "stage15a-acquire        fetch the two published PyPI artifacts and check both digests"
	@echo "stage15a-runtime        build the frozen offline runtime from the local wheelhouse"
	@echo "stage15a-runtime-verify G1: the artifact and runtime closure, re-hashed"
	@echo "stage15a-route          G2: the upstream image-to-score contract, parsed from the installed module"
	@echo "stage15a-qualify        G3: determinism and the failure contract, on non-SD300 fixtures"
	@echo "stage15a-preflight      check every input the 6,000 run will read, and write nothing"
	@echo "stage15a-status         report where the Stage 15A run stands"
	@echo "stage15a-integrity      G6: the integrity pass over the stored outcomes"
	@echo "stage15a-documents      write the seven derivable evidence documents (commit them, then publish)"
	@echo "stage15a-publish        write the marker too; refuses a result set that is not score-bearing"
	@echo "stage16a-contract       the FingerFlow qualification: seven gates, the route authorities, the failure split"
	@echo "stage16a-evidence       verify the committed Stage 16A evidence"
	@echo "stage16a-acquire        fetch the distributions, the nine checkpoints and the pinned sources; check every digest"
	@echo "stage16a-artifacts      G1: the artifact and runtime closure, re-hashed"
	@echo "stage16a-route          G2: the ten route questions, parsed from the pinned upstream sources"
	@echo "stage16a-documents      write the seven derivable evidence documents (write the README, commit, then publish)"
	@echo "stage16a-publish        write the marker too; refuses Algorithm 5 over an unclosed route"
	@echo "stage17a-contract       the fingerprintMatcher qualification: the score contract, parsed"
	@echo "stage17a-evidence       verify the committed Stage 17A evidence"
	@echo "stage17a-acquire        fetch the two published PyPI distributions and check both digests"
	@echo "stage17a-artifacts      G1: both distributions, and the one module they must agree on"
	@echo "stage17a-score          G2: does match_fingerprints return a raw scalar at all"
	@echo "stage17a-documents      write the three derivable evidence documents (commit them, then publish)"
	@echo "stage17a-publish        write the marker too; refuses a score direction over a failed contract"
	@echo "stage8c-workspace       Stage 8C alignment and preflight over the real inputs"
	@echo "stage8c-verify          re-derive and print the Stage 8C evidence-only verification"
	@echo "sourceafis-build        build the SourceAFIS Java bridge"
	@echo "sourceafis-java-test    Java unit tests"
	@echo "sourceafis-python-test  Python SourceAFIS tests, excluding the dataset"
	@echo "sourceafis-test         build + Java tests + Python tests"
	@echo "sourceafis-sd300-smoke  the 24-job real-SD300 pilot (needs FPBENCH_SD300_ROOT)"
	@echo ""
	@echo "nbis-inspect            where the NBIS lock, cache and builds stand"
	@echo "nbis-seal               record the digests of NIST's two archives, once"
	@echo "nbis-fetch              download and verify exactly the locked archives"
	@echo "nbis-build              compile them (no network, no substitute archive)"
	@echo "nbis-certify            NIST's own tests + PNG/PPI probes, then the manifest"
	@echo "nbis-verify             re-check a build against the lock and this repository"
	@echo "nbis-contract           the NBIS route's own contract (no NBIS, no network)"
	@echo "nbis-upstream           the claims only a real certified build can settle"
	@echo "nbis-canonical500-preflight  the stage 7C workspace gate, before and after"
	@echo ""
	@echo "research-prepare        pin the runtime and plan the 6,000-comparison run"
	@echo "research-execute        execute it, resumably (JOBS=n for a slice)"
	@echo "research-status         how far along the evidence chain the run is"
	@echo "research-finalize       revalidate, then write completion, result set, receipt"
	@echo ""
	@echo "decisions-test          threshold, eligibility and view tests (no JVM, no data)"
	@echo "decisions-prepare       pin the source run, the profile and the derivation code"
	@echo "decisions-derive        6,000 decisions, 1,500 eligibility units, 3 views"
	@echo "decisions-status        re-derive the whole chain and report where it stands"
	@echo "decisions-finalize      re-verify, then write the derivation receipt and marker"
	@echo ""
	@echo "metrics-test            count invariants, denominators, pooling, reports"
	@echo "metrics-prepare         pin the decision set, the metric policy and the metric code"
	@echo "metrics-derive          six count families and fourteen metrics, per release and pooled"
	@echo "metrics-status          re-derive every count and rate and report where it stands"
	@echo "metrics-finalize        re-verify, then write summary, report, receipt and marker"
	@echo "metrics-show            print the verified report (refuses anything unverified)"
	@echo ""
	@echo "imaging-test            canonical geometry, pixels, PNG, prepared sets (no JVM, no data)"
	@echo "imaging-fixtures        regenerate the golden imaging fixtures (deliberate act)"
	@echo "canonical-prepare       pin the transform, check 3,000 sources, write the definition"
	@echo "canonical-materialize   produce canonical 500 ppi artefacts (IMAGES=n for a slice)"
	@echo "canonical-status        re-verify the prepared-image set and report where it stands"
	@echo "canonical-finalize      re-verify, then write manifest, receipt and marker"
	@echo ""
	@echo "canonical-run-prepare   plan the 6,000-comparison run over the canonical set"
	@echo "canonical-run-execute   execute it, resumably (JOBS=n for a slice)"
	@echo "canonical-run-status    how far along the evidence chain the canonical run is"
	@echo "canonical-run-finalize  revalidate, then write completion, result set, receipt"

# What CI runs on every push.
test:
	pytest -m "not dataset and not sourceafis and not full_run"

# The checks over what this repository *publishes*, as opposed to what it
# computes: no absolute path in evidence, no rate label on the negative sanity
# fraction, the README describing every published stage, and every fingerprinted
# source pinned to LF. Fast, needs nothing, and each one exists because the
# corresponding claim was made in a document and contradicted by a file.
publication-hygiene:
	pytest tests/contract/test_evidence_carries_no_absolute_paths.py 	       tests/contract/test_published_workbooks_obey_adr0030.py 	       tests/contract/test_stage_registry.py 	       tests/contract/test_source_fingerprints_are_pinned.py -q

test-all:
	pytest

full-run:
	pytest -m full_run

# The suite a new algorithm's author runs first: the shared adapter tools, the
# conformance checks, the generic research engine, the import boundaries and the
# SourceAFIS descriptor regression. Needs no dataset and no JVM.
adapter-contract:
	pytest -m "adapter_contract and not dataset" -q

# ------------------------------------------------------------------------- NBIS

# NIST NBIS 5.0.0 — MINDTCT into BOZORTH3, as one algorithm identity
# (docs/adr/0046). Five build commands rather than one, because obtaining a
# source, verifying it, compiling it and certifying it fail for entirely
# different reasons and must stop at different points
# (integrations/nbis/README.md).
NBIS := python integrations/nbis/build.py

nbis-inspect:
	$(NBIS) inspect

# Run once, by a person, with the archives NIST distributes. RELEASE= and TESTS=
# are the local paths; RELEASE_URL= and TESTS_URL= are the URLs they came from.
nbis-seal:
	$(NBIS) seal --release "$(RELEASE)" --release-url "$(RELEASE_URL)" \
	             --tests "$(TESTS)" --tests-url "$(TESTS_URL)"

nbis-fetch:
	$(NBIS) fetch

nbis-build:
	$(NBIS) build

# The step that produces the build manifest. Until it passes there is no
# certified build, and the adapter has no way to use one.
nbis-certify:
	$(NBIS) test

# BUILD=build/nbis-5.0.0/<build-id>. CI runs this after every cache restore.
nbis-verify:
	python integrations/nbis/verify_build.py "$(BUILD)"

# The parsers, the failure mapping, the cleanup, the shared timeout, the stored
# metadata, the command construction and the runtime guard. No NBIS, no network.
nbis-contract:
	pytest -m "nbis_contract and not upstream and not dataset" -q

# PNG support, the PPI policy, determinism, the score of zero, NIST's own suite,
# the real conformance run and a research smoke run. Needs FPBENCH_NBIS_BUILD_DIR
# or exactly one certified build under build/nbis-5.0.0/.
nbis-upstream:
	pytest -m nbis_upstream -q

# The stage 7C workspace, before and after the run: the reference chain, the
# prepared set, the alignment at 6,000/6,000 and 3,000/3,000, the pinned build,
# and — once a run exists — that nothing downstream of its raw scores was made.
nbis-canonical500-preflight:
	pytest -m nbis_full_run -q

# ---------------------------------------------------------------- stage 7D

# The comparison methodology, without either algorithm and without the dataset:
# strict comparators and their boundary, the frozen SourceAFIS profile
# identities, the algorithm-neutral orchestration, the comparison policy's
# refusals, the population rules and the tampering cases.
stage7d-contract:
	pytest -m "stage7d_contract and not dataset" -q

# The same methodology over the real 12,000 stored results and both finished
# evidence trees. Run after every evidence commit (spec section 87).
stage7d-workspace:
	pytest -m "dataset and stage7d" -q

# ---------------------------------------------------------------- stage 8A

# Artifact qualification only: immutable models, hard gates, offline fixture
# probes, selection ordering, negative cases, and tampering.  It has no route to
# SD300 or to the result/derivation workspaces.
stage8a-contract:
	pytest -m "stage8a_contract" -q

# The committed evidence is mandatory and may never skip.  A missing report,
# altered acquisition manifest, policy change, or stale finalization fails.
stage8a-workspace:
	pytest -m "stage8a" -q

stage8a-status:
	python -m fpbench.experiments.stage8a_modern_matcher_selection status

# ---------------------------------------------------------------- stage 8B

# The frozen protocol only: identities, profile schemas, the declared transform,
# the score contract, the subprocess protocol, negative cases and tampering.
# No torch, no checkpoint, no network, no dataset — it runs anywhere.
stage8b-contract:
	pytest -m "stage8b_contract" -q

# The committed evidence is mandatory and may never skip.
stage8b-workspace:
	pytest -m "stage8b" -q

stage8b-status:
	python -m fpbench.experiments.stage8b_flx_runtime_qualification status

# ---------------------------------------------------------------------- Stage 8C
#
# The 6,000-comparison run itself is deliberately absent from this file. It takes
# hours, it may not be started under a different commit than it was prepared
# under, and a convenient target is exactly how that happens by accident. The
# documented invocation is docs/experiments/flx-canonical500-raw.md.
stage8c-contract:
	pytest -m "stage8c_contract" -q

# The committed evidence is mandatory and may never skip.
stage8c-evidence:
	pytest -m "stage8c" -q

stage8c-workspace:
	pytest -m "stage8c_full_run" -q

stage8c-verify:
	python -c "from fpbench.experiments.stage8c_verify import verify_stage8c_evidence as v; print(v())"

# ------------------------------------------------------------------ Stage 8D

# Everything here is pure Python over synthetic fixtures. There is no dataset, no
# runtime, no checkpoint and no workspace target, because Stage 8D calibrates
# nothing — and a `stage8d-calibrate` target is exactly how that would stop being
# true by accident (docs/adr/0078).
stage8d-contract:
	pytest -m "stage8d_contract" -q

# The committed evidence is mandatory and may never skip.
stage8d-evidence:
	pytest -m "stage8d" -q

stage8d-qualify:
	python -c "from fpbench.experiments.stage8d_calibration_infrastructure import run_synthetic_qualification as q; r = q(); print(r.qualification_fingerprint, len(r.cases), 'cases')"

# ------------------------------------------------------------------- stage 8E

# The repository-wide research-only third-party usage policy (docs/adr/0081-0084).
# Two write targets rather than one, because the marker is derived against the
# exact bytes of the other five documents and therefore has to come after them:
# `stage8e-documents`, commit, `stage8e-publish`, commit. `stage8e-publish`
# refuses a dirty tree, which is what makes the marker's commit meaningful.
stage8e-contract:
	pytest -m "stage8e_contract" -q

stage8e-evidence:
	pytest -m "stage8e" -q

stage8e-status:
	python -m fpbench.experiments.stage8e_finalization status

stage8e-guard:
	python -c "from pathlib import Path; from fpbench.third_party import require_no_third_party_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files,', len(a.findings), 'third-party bytes')"

stage8e-documents:
	python -m fpbench.experiments.stage8e_finalization documents

stage8e-publish:
	python -m fpbench.experiments.stage8e_finalization publish

# ------------------------------------------------------------------- stage 9A

# The FLARE full-route artifact and method qualification (docs/adr/0085-0088).
# Same two-write shape as Stage 8E: `stage9a-documents`, commit,
# `stage9a-publish`, commit.
#
# `stage9a-acquire` is the only target in this file that reaches the network,
# and it runs on the project owner's machine and nowhere else. CI fetches no
# restricted artifact. `stage9a-enroll` reports the digest and size a
# newly-acquired artifact would need frozen in stage9a_flare_identity; freezing
# them is a reviewed edit, never something the code does to itself.
stage9a-contract:
	pytest -m "stage9a_contract" -q

stage9a-evidence:
	pytest -m "stage9a" -q

stage9a-artifacts:
	pytest -m "flare_artifact" -q -rs

stage9a-status:
	python -m fpbench.experiments.stage9a_flare_finalization status

stage9a-guard:
	python -c "from pathlib import Path; from fpbench.experiments.stage9a_flare_qualification import require_no_flare_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files scanned against', a.known_digest_count, 'exact FLARE digests,', len(a.findings), 'findings')"

stage9a-acquire:
	python -c "from pathlib import Path; from fpbench.experiments import stage9a_flare_artifacts as a, stage9a_flare_identity as f; [print(x.artifact_id, '->', a.acquire_artifact(x, repository_root=Path('.')).name) for x in f.REQUIRED_ARTIFACTS]"

stage9a-enroll:
	python -c "from pathlib import Path; from fpbench.experiments import stage9a_flare_artifacts as a, stage9a_flare_identity as f; [print(x.artifact_id, *a.enroll_artifact(x, repository_root=Path('.'))) for x in f.REQUIRED_ARTIFACTS if not x.identity_established]"

stage9a-documents:
	python -m fpbench.experiments.stage9a_flare_finalization documents

stage9a-publish:
	python -m fpbench.experiments.stage9a_flare_finalization publish

# ------------------------------------------------------------------ stage 10A

# The Algorithm 4 candidate preflight (docs/adr/0089-0093). Same two-write shape
# as Stage 8E and Stage 9A: `stage10a-documents`, commit, `stage10a-publish`,
# commit.
#
# There is no `stage10a-acquire`. Neither candidate reached the artifact gate,
# so nothing is fetched — that is the stage's result, and a convenient target
# for fetching is exactly how it would stop being true by accident.
stage10a-contract:
	pytest -m "stage10a_contract" -q

stage10a-evidence:
	pytest -m "stage10a" -q

stage10a-artifacts:
	pytest -m "algorithm4_preflight_artifact" -q -rs

stage10a-status:
	python -m fpbench.experiments.stage10a_finalization status

stage10a-guard:
	python -c "from pathlib import Path; from fpbench.experiments.stage10a_preflight import require_no_candidate_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files scanned against', a.known_digest_count, 'exact candidate digests,', len(a.findings), 'findings')"

stage10a-documents:
	python -m fpbench.experiments.stage10a_finalization documents

stage10a-publish:
	python -m fpbench.experiments.stage10a_finalization publish

# ------------------------------------------------------------------ stage 10B

# The id3 Finger SDK preflight and access qualification (docs/adr/0094-0098).
# Same two-write shape as Stage 8E, Stage 9A and Stage 10A: `stage10b-documents`,
# commit, `stage10b-publish`, commit.
#
# There is no `stage10b-acquire`. The package and the licence arrive together
# through a request a person makes to the vendor, in their own name, and a
# convenient target for it would be a target that puts credentials one flag away
# from a script (docs/adr/0098).
stage10b-contract:
	pytest -m "stage10b_contract" -q

stage10b-evidence:
	pytest -m "stage10b" -q

stage10b-artifacts:
	pytest -m "id3_artifact" -q -rs

stage10b-status:
	python -m fpbench.experiments.stage10b_finalization status

stage10b-guard:
	python -c "from pathlib import Path; from fpbench.experiments.stage10b_preflight import require_no_id3_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files scanned against', a.known_digest_count, 'exact id3 digests and the vendor artifact name rules,', len(a.findings), 'findings')"

stage10b-documents:
	python -m fpbench.experiments.stage10b_finalization documents

stage10b-publish:
	python -m fpbench.experiments.stage10b_finalization publish

# ------------------------------------------------------------------ stage 11A

# The VeriFinger 2025.2 artifact and API preflight (docs/adr/0099-0103). Same
# two-write shape as every stage since 8D: `stage11a-documents`, commit,
# `stage11a-publish`, commit.
#
# Unlike Stage 10B there *is* an acquire target, because Neurotechnology
# publishes a direct locator that needs no account, no form and no approval
# (docs/adr/0100). It fetches about 4.8 GB into the local artifact store, outside
# the repository, and verifies both artifacts by size and SHA-256.
#
# There is no activate target and there will not be one. Activation starts a
# 30-day trial bound to one machine and excludes other licensed Neurotechnology
# products on it; that is the maintainer's decision, taken once, by hand.
stage11a-contract:
	pytest -m "stage11a_contract" -q

stage11a-evidence:
	pytest -m "stage11a" -q

stage11a-artifacts:
	pytest -m "verifinger_artifact" -q -rs

stage11a-status:
	python -m fpbench.experiments.stage11a_finalization status

stage11a-acquire:
	python -c "import json, urllib.request; from pathlib import Path; from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path, inspect_local_artifact; from fpbench.experiments.stage11a_verifinger_observations import ACQUIRED_ARTIFACTS; d = artifact_store_prefix_path(); d.mkdir(parents=True, exist_ok=True); [urllib.request.urlretrieve(a.locator, d / a.filename) for a in ACQUIRED_ARTIFACTS if not (d / a.filename).is_file()]; [print(inspect_local_artifact(a).presence.value, a.filename) for a in ACQUIRED_ARTIFACTS]"

stage11a-verify:
	python -c "from pathlib import Path; from fpbench.experiments.stage11a_artifacts import acquisition_state as s; a = s(repository_root=Path('.')); print('obtained', a.obtained); [print(' ', i.presence.value, i.filename, i.detail) for i in a.states]"

stage11a-guard:
	python -c "from pathlib import Path; from fpbench.experiments.stage11a_artifacts import require_no_verifinger_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files scanned against', a.known_digest_count, 'exact VeriFinger digests and the vendor artifact name rules,', len(a.findings), 'findings')"

# The bounded local qualification run. `qualify-check` reports the three
# preconditions and writes nothing, which is what to run before deciding
# whether to start a 30-day clock; `qualify` performs the pass and writes the
# record beside the artifacts, outside the repository. Neither is ever run in
# CI (docs/adr/0104).
stage11a-qualify-check:
	python -m fpbench.experiments.stage11a_qualification check

stage11a-qualify:
	python -m fpbench.experiments.stage11a_qualification run

stage11a-documents:
	python -m fpbench.experiments.stage11a_finalization documents

stage11a-publish:
	python -m fpbench.experiments.stage11a_finalization publish

# ------------------------------------------------------------------ stage 11B

# VeriFinger 2025.2 as the benchmark's fourth algorithm: the production adapter,
# the exact runtime closure, and the canonical 6,000 raw comparisons.
#
# The 6,000-comparison run itself is deliberately absent from this file. It takes
# hours, it may not be started under a different commit than it was prepared
# under, and a convenient target is exactly how that happens by accident. The
# documented invocation is docs/experiments/verifinger-canonical500-raw.md.
#
# Same two-write shape as every stage since 8D: `stage11b-documents`, commit,
# `stage11b-publish`, commit.
stage11b-contract:
	pytest -m "stage11b_contract" -q

# The committed evidence is mandatory and may never skip.
stage11b-evidence:
	pytest -m "stage11b" -q

stage11b-artifacts:
	pytest -m "verifinger_artifact" -q -rs

# Builds the bridge jar from the pinned bindings. Never shades a vendor jar in:
# the Neurotechnology jars stay on the classpath, where the runtime manifest
# pins every one of them by digest.
verifinger-build:
	python integrations/verifinger-java/build.py

verifinger-runtime-verify:
	python -m fpbench.experiments.verifinger_runtime_manifest verify

# The production adapter's own smoke, on fixtures that are not SD300. Never run
# in CI: it needs the pinned SDK and an activated trial licence.
stage11b-smoke:
	python -m fpbench.experiments.verifinger_smoke

stage11b-preflight:
	python -c "import json; from pathlib import Path; from fpbench.experiments.verifinger_canonical500_full import preflight_verifinger_canonical500_run as p; print(json.dumps({k: v for k, v in p(repository_root=Path('.')).items() if k != 'production_smoke'}, indent=2, default=str))"

stage11b-status:
	python -c "from pathlib import Path; from fpbench.experiments.verifinger_canonical500_full import inspect_verifinger_canonical500_experiment as i; s = i(repository_root=Path('.')); print(s.status, s.run_id)"

stage11b-verify:
	python -m fpbench.experiments.stage11b_finalization verify

stage11b-documents:
	python -m fpbench.experiments.stage11b_finalization publish

stage11b-publish:
	python -m fpbench.experiments.stage11b_finalization finalize

# ------------------------------------------------------------------ stage 12A

# The Innovatrics IDKit acquisition and API preflight (docs/adr/0107-0111). Same
# two-write shape as every stage since 8D: `stage12a-documents`, commit,
# `stage12a-publish`, commit. The vendor refusal makes the outcome final.
#
# There is no acquire target and there cannot be one. Innovatrics delivers
# through a customer portal. A request made in the maintainer's own name received
# an explicit policy refusal. `stage12a-acquire` below reports that categorical
# status; it fetches nothing and exposes no correspondence or contact identity.
#
# There is no activate target either. A licence is machine-bound and
# time-limited, and generating one before the harness compiles would spend a
# clock on build errors (docs/adr/0111).
stage12a-contract:
	pytest -m "stage12a_contract" -q

stage12a-evidence:
	pytest -m "stage12a" -q

stage12a-artifacts:
	pytest -m "idkit_artifact" -q -rs

stage12a-status:
	python -m fpbench.experiments.stage12a_finalization status

stage12a-acquire:
	python -c "from pathlib import Path; from fpbench.experiments.stage12a_acquisition import acquisition_state; from fpbench.experiments.stage12a_idkit_observations import route_rows, WHAT_WOULD_CHANGE_THE_STATUS; s = acquisition_state(repository_root=Path('.')); print('status  ', s.status.value); print('package ', s.presence.value); [print(' ', r['outcome'].ljust(34), r['route_id']) for r in route_rows()]; print('remaining acquisition actions:', len(WHAT_WOULD_CHANGE_THE_STATUS))"

stage12a-guard:
	python -c "from pathlib import Path; from fpbench.experiments.stage12a_preflight import require_no_idkit_bytes_in_git as g; a = g(Path('.')); print(a.tracked_file_count, 'tracked files scanned against the vendor artifact and licence name rules,', len(a.findings), 'findings')"

# The qualification harness. `qualify-fake` drives every pass against the fake
# SDK and needs no package, no licence and no network — it is what CI runs, and
# what proves the harness before a licence clock is ever started. `qualify` is
# the same driver against a delivered binding, and refuses while there is none.
stage12a-qualify-fake:
	python -m fpbench.experiments.stage12a_qualification fake

stage12a-qualify:
	python -m fpbench.experiments.stage12a_qualification check

stage12a-documents:
	python -m fpbench.experiments.stage12a_finalization documents

stage12a-publish:
	python -m fpbench.experiments.stage12a_finalization publish

# ------------------------------------------------- Stage 13A: FingerCell preflight
#
# The first Algorithm 5 candidate whose acquisition needs nobody's permission:
# Neurotechnology publishes a direct FingerCell trial download, so there is no
# vendor-pending state here at all. What replaces it is `ACTION_REQUIRED`, which
# means a local step this project can perform has not been performed yet — and
# never that something is wrong with the candidate (docs/adr/0112).
#
# The order matters and is not an accident. `stage13a-acquire` fetches nothing by
# itself: the archive is downloaded deliberately, then declared, then unpacked and
# inventoried, and only then is the bridge compiled. Activation comes last, so the
# 30-day clock does not run while the harness is debugged (docs/adr/0115).

stage13a-contract:
	pytest -m "stage13a_contract" -q

stage13a-evidence:
	pytest -m "stage13a" -q

stage13a-artifacts:
	pytest -m "fingercell_artifact" -q -rs

stage13a-status:
	python -m fpbench.experiments.stage13a_finalization status

stage13a-acquire:
	python -m fpbench.experiments.stage13a_acquisition state

stage13a-declare:
	python -m fpbench.experiments.stage13a_acquisition declare --filename "$(ARCHIVE)"

stage13a-guard:
	python -m fpbench.experiments.stage13a_acquisition guard

stage13a-contamination:
	python -c "from pathlib import Path; from fpbench.experiments.stage13a_preflight import require_no_verifinger_contamination as g; print(len(g(Path('.'))), 'Stage 13A modules audited; none reaches Algorithm 4')"

stage13a-qualify-fake:
	python -m fpbench.experiments.stage13a_qualification fake

stage13a-qualify:
	python -m fpbench.experiments.stage13a_qualification check

stage13a-documents:
	python -m fpbench.experiments.stage13a_finalization documents

stage13a-publish:
	python -m fpbench.experiments.stage13a_finalization publish

# ---------------------------------------------------- Stage 14A: Griaule preflight
#
# The smallest candidate stage since 8A, and deliberately so. Stages 12A and 13A
# each built ten gates and a qualification harness for a candidate that never
# produced one comparison, so this one asks the four questions that could
# disqualify Griaule and builds nothing else until they are answered
# (docs/adr/0123).
#
# There is no bridge target here, no adapter and no fake engine, because there is
# nothing yet to build one against. `stage14a-acquire` fetches nothing: Griaule
# publishes no self-service download, so acquisition is a request somebody sends,
# and its status is a frozen constant a maintainer edits when they send it
# (docs/adr/0121).

stage14a-contract:
	pytest -m "stage14a_contract" -q

stage14a-evidence:
	pytest -m "stage14a" -q

stage14a-status:
	python -m fpbench.experiments.stage14a_finalization status

stage14a-acquire:
	python -m fpbench.experiments.stage14a_acquisition state

stage14a-declare:
	python -m fpbench.experiments.stage14a_acquisition declare \
		--filename "$(PACKAGE)" --locator "$(LOCATOR)" \
		--locator-category "$(CHANNEL)" --product-version "$(VERSION)" \
		--build "$(BUILD)" --platform "$(PLATFORM)" --obtained-utc "$(OBTAINED)"

stage14a-guard:
	python -m fpbench.experiments.stage14a_acquisition guard

stage14a-artifacts:
	pytest -m "griaule_artifact" -q -rs

stage14a-documents:
	python -m fpbench.experiments.stage14a_finalization documents

stage14a-publish:
	python -m fpbench.experiments.stage14a_finalization publish

# ------------------------------------------------------------------- SourceAFIS

# One command, as the spec requires. The wrapper pins the Maven version; the pom pins
# everything else.
sourceafis-build:
	$(MVNW) --batch-mode --file $(POM) clean test package

sourceafis-java-test:
	$(MVNW) --batch-mode --file $(POM) test

# FPBENCH_REQUIRE_SOURCEAFIS makes a missing JVM or an unbuilt jar fail rather than
# skip. Without it a broken build would produce a green run full of skips.
sourceafis-python-test:
	FPBENCH_REQUIRE_SOURCEAFIS=1 pytest -m "sourceafis and not dataset"

sourceafis-test: sourceafis-build sourceafis-python-test

sourceafis-sd300-smoke:
	FPBENCH_REQUIRE_SOURCEAFIS=1 pytest -m "sourceafis and dataset" -v

# --------------------------------------------------------------- research run

# The stage 4B full run. Four commands rather than one, because a dirty working
# tree, an unverified dataset or a replaced jar must stop the run at a different
# point from a comparison that simply has not happened yet (docs/adr/0020).
#
# All of them need FPBENCH_SD300_ROOT, a built bridge, and a clean committed
# source tree. `prepare` hashes the delivery the first time it runs.
RESEARCH := python -m fpbench.experiments.sourceafis_native_full

research-prepare:
	$(RESEARCH) prepare

# JOBS=500 executes a slice; omit it to finish the plan.
research-execute:
	$(RESEARCH) execute $(if $(JOBS),--max-new-jobs $(JOBS),)

research-status:
	$(RESEARCH) status

research-finalize:
	$(RESEARCH) finalize

# ----------------------------------------------------------------- decisions

# Applying a documented threshold to a finished run. No Java and no dataset:
# decisions are derived from stored scores (docs/adr/0021).
DECISIONS := python -m fpbench.experiments.sourceafis_native_decisions

decisions-test:
	pytest -m "decisions and not dataset"

decisions-prepare:
	$(DECISIONS) prepare

decisions-derive:
	$(DECISIONS) derive

decisions-status:
	$(DECISIONS) status

decisions-finalize:
	$(DECISIONS) finalize

# ------------------------------------------------------------------- metrics

# Counting a finished derivation under an immutable metric policy. No Java, no
# dataset, and no threshold: this stage reads decisions, it does not make them
# (docs/adr/0026).
METRICS := python -m fpbench.experiments.sourceafis_native_evaluation

metrics-test:
	pytest -m "metrics and not dataset"

metrics-prepare:
	$(METRICS) prepare

metrics-derive:
	$(METRICS) derive

metrics-status:
	$(METRICS) status

metrics-finalize:
	$(METRICS) finalize

metrics-show:
	$(METRICS) show

# ------------------------------------------------------------------- imaging

# The shared canonical 500 ppi input pipeline. No JVM and no algorithm: this
# stage produces images every matcher is handed, not results (docs/adr/0031).
CANONICAL_IMAGES := python -m fpbench.experiments.sd300_canonical500_images

imaging-test:
	pytest -m "imaging and not dataset and not sourceafis"

# Regenerating the golden fixtures is a deliberate act with a reviewed diff. CI
# runs this and fails on any change.
imaging-fixtures:
	python tests/fixtures/imaging/generate.py

canonical-prepare:
	$(CANONICAL_IMAGES) prepare

# IMAGES=500 materialises a slice; omit it to finish the set.
canonical-materialize:
	$(CANONICAL_IMAGES) materialize $(if $(IMAGES),--max-new-images $(IMAGES),)

canonical-status:
	$(CANONICAL_IMAGES) status

canonical-finalize:
	$(CANONICAL_IMAGES) finalize

# ------------------------------------------------------- canonical 500 run

# The same 6,000 comparisons as the native run, over the canonical input set.
# Needs a PREPARATION_READY set and its exact id written into
# configs/execution/canonical_500_lanczos3_60s_v1.yaml.
CANONICAL_RUN := python -m fpbench.experiments.sourceafis_canonical500_full

canonical-run-prepare:
	$(CANONICAL_RUN) prepare

canonical-run-execute:
	$(CANONICAL_RUN) execute $(if $(JOBS),--max-new-jobs $(JOBS),)

canonical-run-status:
	$(CANONICAL_RUN) status

canonical-run-finalize:
	$(CANONICAL_RUN) finalize

# ------------------------------------------------- Stage 15A: fingerprints-matching
#
# The first Algorithm 5 candidate that needs nobody's permission and nobody's
# answer. Self-service acquisition and runnability without vendor action became
# hard requirements after three consecutive stages ended at a vendor, and this
# candidate is a 4,492-byte MIT package on PyPI (docs/adr/0126).
#
# The 6,000-comparison run is deliberately absent from this file, exactly as it
# is for Stage 11B. It may not be started under a different commit than it was
# prepared under, and a convenient target is how that happens by accident. The
# documented invocation is docs/experiments/fingerprints-matching-canonical500-raw.md.
#
# Order matters. `acquire` fetches the artifacts, `runtime` builds the frozen
# environment from the local wheelhouse with --no-index, and only then can G1
# pass. Everything after that reads bytes that are already pinned.

STAGE15A := python -m fpbench.experiments.stage15a_publish

stage15a-contract:
	pytest -m "stage15a_contract" -q

# The committed evidence is mandatory and may never skip.
stage15a-evidence:
	pytest -m "stage15a" -q

stage15a-artifacts:
	pytest -m "fingerprints_matching_artifact" -q -rs

# Fetches the two published distributions into the local store and checks both
# digests against the frozen identity. Never run in CI: the store lives outside
# the repository and no runner has one.
stage15a-acquire:
	python -m fpbench.experiments.stage15a_acquire

# Builds the frozen environment from the local wheelhouse, offline. After this
# the runtime never reaches the network again.
stage15a-runtime:
	python -m fpbench.experiments.stage15a_acquire runtime

stage15a-runtime-verify:
	python -m fpbench.experiments.stage15a_runtime verify

stage15a-route:
	python -m fpbench.experiments.stage15a_route

stage15a-qualify:
	python -m fpbench.experiments.stage15a_qualification

stage15a-preflight:
	$(STAGE15A) preflight

stage15a-status:
	$(STAGE15A) status

stage15a-integrity:
	$(STAGE15A) integrity

stage15a-verify:
	$(STAGE15A) verify

stage15a-documents:
	$(STAGE15A) documents

stage15a-publish:
	$(STAGE15A) publish

STAGE16A := python -m fpbench.experiments.stage16a_finalization

stage16a-contract:
	pytest -m "stage16a_contract" -q

stage16a-evidence:
	pytest -m "stage16a" -q

stage16a-acquire:
	python -m fpbench.experiments.stage16a_acquire

stage16a-artifacts:
	python -m fpbench.experiments.stage16a_artifacts

stage16a-route:
	python -m fpbench.experiments.stage16a_route

stage16a-verify:
	$(STAGE16A) verify

stage16a-documents:
	$(STAGE16A) documents

stage16a-publish:
	$(STAGE16A) publish

STAGE17A := python -m fpbench.experiments.stage17a_finalization

stage17a-contract:
	pytest -m "stage17a_contract" -q

stage17a-evidence:
	pytest -m "stage17a" -q

stage17a-acquire:
	python -m fpbench.experiments.stage17a_acquire

stage17a-artifacts:
	python -m fpbench.experiments.stage17a_score_contract artifacts

stage17a-score:
	python -m fpbench.experiments.stage17a_score_contract score

stage17a-verify:
	$(STAGE17A) verify

stage17a-documents:
	$(STAGE17A) documents

stage17a-publish:
	$(STAGE17A) publish

STAGE18A := python -m fpbench.experiments.stage18a_reference_run

stage18a-contract:
	pytest -m "stage18a_contract" -q

stage18a-evidence:
	pytest -m "stage18a" -q

# Build the OpenAFIS raw 1:1 bridge. Needs FPBENCH_OPENAFIS_SOURCE pointing at the
# pinned checkout; the binary lands in integrations/openafis/build/ and is ignored.
stage18a-bridge:
	$(MAKE) -C integrations/openafis all

stage18a-status:
	$(STAGE18A) status

stage18a-extract:
	$(STAGE18A) extract

stage18a-match:
	$(STAGE18A) match

stage18a-run:
	$(STAGE18A) run

stage18a-receipt:
	$(STAGE18A) receipt

stage18a-diagnostics:
	python -m fpbench.experiments.stage18a_diagnostics

# --------------------------------------------------------------------- Stage 19A
#
# Algorithm 5: MINDTCT -> OpenAFIS. The extractor and the matcher are both Linux
# binaries, so the run happens inside the NBIS build distro; the targets below are
# the Windows-side entry points and delegate there.

stage19a-contract:
	pytest -m "stage19a_contract" -q

stage19a-evidence:
	pytest -m "stage19a" -q

# The four checks section 12 asks for, before the full run and no more.
stage19a-smoke:
	python scripts/stage19a_smoke.py

# MINDTCT over all 3,000 canonical images, recording minutiae counts only. A
# measurement, not a pilot: it produces no score and cannot change the route.
stage19a-survey:
	python scripts/stage19a_minutiae_survey.py

# The 6,000 canonical comparisons, driven only through the adapter contract.
stage19a-run:
	python scripts/stage19a_canonical_run.py

stage19a-diagnostics:
	python -m fpbench.experiments.stage19a_diagnostics \
	  --outcomes $(FPBENCH_STAGE19A_ROOT)/pair-outcomes.jsonl \
	  --algorithm2-results workspace/results/run_f0468f28ffba/raw \
	  --output $(FPBENCH_STAGE19A_ROOT)/diagnostic-report.json

stage19a-documents:
	python -m fpbench.experiments.stage19a_finalization \
	  --diagnostics $(FPBENCH_STAGE19A_ROOT)/diagnostic-report.json \
	  --outcomes $(FPBENCH_STAGE19A_ROOT)/pair-outcomes.jsonl

# --------------------------------------------------------------------- Stage 19B
#
# The capacity extension: one disabled refusal in OpenAFIS, and proof it is the
# only change. Gate A must pass before the run — if it fails there is no second
# patch.

stage19b-contract:
	pytest -m "stage19b_contract" -q

stage19b-evidence:
	pytest -m "stage19b" -q

# Patch the pinned tree and build the capacity-extended bridge.
stage19b-build:
	bash integrations/openafis/build_capacity_extended.sh

# The 1,583-pair exact inertness test. Must pass before anything else runs.
stage19b-gate-a:
	python scripts/stage19b_gate_a.py

stage19b-run:
	python scripts/stage19b_canonical_run.py

stage19b-determinism:
	python scripts/stage19b_determinism.py

stage19b-diagnostics:
	python -m fpbench.experiments.stage19b_diagnostics \
	  --outcomes $(FPBENCH_STAGE19B_ROOT)/pair-outcomes.jsonl \
	  --stage19a-outcomes $(FPBENCH_STAGE19A_ROOT)/pair-outcomes.jsonl \
	  --algorithm2-results workspace/results/run_f0468f28ffba/raw \
	  --output $(FPBENCH_STAGE19B_ROOT)/diagnostic-report.json

stage19b-documents:
	python -m fpbench.experiments.stage19b_finalization \
	  --gate-a $(FPBENCH_STAGE19B_ROOT)/gate-a.json \
	  --diagnostics $(FPBENCH_STAGE19B_ROOT)/diagnostic-report.json \
	  --patch $(FPBENCH_STAGE19B_ROOT)/patch-provenance.json \
	  --translator-inertness $(FPBENCH_STAGE19B_ROOT)/translator-inertness.json \
	  --outcomes $(FPBENCH_STAGE19B_ROOT)/pair-outcomes.jsonl

# --------------------------------------------------------------------- Stage 20A
#
# Official University of Bologna MCC SDK v2.0 preflight. Vendor bytes, probe
# binaries and full probe output remain in the local third-party store. This
# stage uses the SDK's sample minutiae only and never reads SD300.

stage20a-contract:
	pytest -m "stage20a_contract" -q

stage20a-evidence:
	pytest -m "stage20a" -q

stage20a-acquire:
	python scripts/stage20a_mcc_sdk_preflight.py acquire
	python scripts/stage20a_mcc_sdk_preflight.py extract

stage20a-probe:
	python scripts/stage20a_mcc_sdk_preflight.py probe

stage20a-publish:
	python scripts/stage20a_mcc_sdk_preflight.py publish

stage20a-verify:
	python scripts/stage20a_mcc_sdk_preflight.py verify

# --------------------------------------------------------------------- Stage 20B
#
# The production route Stage 20A qualified. MINDTCT is the certified Linux build
# Algorithm 2 runs, so the run happens inside the NBIS build distro and reaches
# the Windows MCC bridge through WSL interop; stage20b-build and stage20b-gate-a
# run on the Windows side, where the .NET Framework compiler is.
#
# Two gates and no more. If either fails, the 6,000 do not run.

stage20b-contract:
	pytest -m "stage20b_contract" -q

stage20b-evidence:
	pytest -m "stage20b" -q

stage20b-build:
	python scripts/stage20b_gate_a.py --build

stage20b-gate-a:
	python scripts/stage20b_gate_a.py

stage20b-gate-b:
	python scripts/stage20b_gate_b.py

stage20b-environment:
	python scripts/stage20b_environment.py

stage20b-run:
	python scripts/stage20b_canonical_run.py

stage20b-publish:
	python scripts/stage20b_publish.py
