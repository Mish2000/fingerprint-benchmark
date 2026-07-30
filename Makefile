# Convenience targets. Everything here is a one-liner someone would otherwise have to
# remember; nothing here is load-bearing logic.

MVNW := ./integrations/sourceafis-java/mvnw
POM := integrations/sourceafis-java/pom.xml
BRIDGE_JAR := integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar

.PHONY: help test test-all full-run \
        sourceafis-build sourceafis-java-test sourceafis-python-test \
        sourceafis-test sourceafis-sd300-smoke \
        research-prepare research-execute research-status research-finalize

help:
	@echo "test                    unit + integration, no dataset, no Java, no full run"
	@echo "test-all                everything available on this machine"
	@echo "full-run                the 6,000-job dummy protocol (minutes)"
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

# What CI runs on every push.
test:
	pytest -m "not dataset and not sourceafis and not full_run"

test-all:
	pytest

full-run:
	pytest -m full_run

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
