# Convenience targets. Everything here is a one-liner someone would otherwise have to
# remember; nothing here is load-bearing logic.

MVNW := ./integrations/sourceafis-java/mvnw
POM := integrations/sourceafis-java/pom.xml
BRIDGE_JAR := integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar

.PHONY: help test test-all full-run adapter-contract \
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
	@echo "sourceafis-build        build the SourceAFIS Java bridge"
	@echo "sourceafis-java-test    Java unit tests"
	@echo "sourceafis-python-test  Python SourceAFIS tests, excluding the dataset"
	@echo "sourceafis-test         build + Java tests + Python tests"
	@echo "sourceafis-sd300-smoke  the 24-job real-SD300 pilot (needs FPBENCH_SD300_ROOT)"
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
