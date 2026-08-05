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
        canonical-run-finalize

help:
	@echo "test                    unit + integration, no dataset, no Java, no full run"
	@echo "test-all                everything available on this machine"
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
