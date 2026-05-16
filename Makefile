# Developer-facing make targets. CI doesn't use these — CI uses `uv run pytest`
# and `uv run python scripts/check_coverage_thresholds.py` directly.

.PHONY: help refresh-cassettes check-cassettes-fresh check-drift

help:
	@echo "Targets:"
	@echo "  refresh-cassettes      Re-record every contract cassette against api.gandi.net."
	@echo "                         Requires GANDI_TOKEN in env (use \`pass show gandi/pat-sandbox\`)."
	@echo "  check-cassettes-fresh  Fail if any cassette is older than 180 days."
	@echo "  check-drift            Re-record to staging dir + structurally diff vs committed."
	@echo "                         Requires GANDI_TOKEN. Never swaps. Pass"
	@echo "                         CASSETTE_DRIFT_OPEN_ISSUE=1 to open/append a drift issue."

# Re-record every cassette. Stages to cassettes.new so a mid-run failure
# never leaves the committed tree in a half-deleted state.
refresh-cassettes:
	@if [ -z "$$GANDI_TOKEN" ]; then \
		echo "GANDI_TOKEN not set. Recording requires a sandbox PAT scoped to teamrocket.network."; \
		echo "Example: GANDI_TOKEN=\$$(pass show gandi/pat-sandbox) make refresh-cassettes"; \
		exit 2; \
	fi
	rm -rf tests/contract/cassettes.new
	mkdir -p tests/contract/cassettes.new
	VCR_CASSETTE_DIR=tests/contract/cassettes.new \
		uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
	rm -rf tests/contract/cassettes
	mv tests/contract/cassettes.new tests/contract/cassettes
	@echo
	@echo "Cassettes recorded. Review the diff (git diff -- tests/contract/cassettes/)"
	@echo "for unredacted PII before committing."

# Warn (don't fail the build) when any cassette is >180 days old.
check-cassettes-fresh:
	@find tests/contract/cassettes -name '*.yaml' -mtime +180 -print 2>/dev/null | \
		awk 'NR { print "STALE: " $$0 } END { \
			if (NR) { print "\nRun: make refresh-cassettes"; exit 1 } \
			else { print "All cassettes fresh (<=180 days)." } }'

# Re-record cassettes to staging dir and structurally diff against the committed
# tree. NEVER swaps the staging dir into place — that's `make refresh-cassettes`.
# Pass CASSETTE_DRIFT_OPEN_ISSUE=1 to open/append a drift-labeled GitHub issue.
check-drift:
	@if [ -z "$$GANDI_TOKEN" ]; then \
		echo "GANDI_TOKEN not set. Drift check requires the same sandbox PAT as refresh-cassettes."; \
		echo "Example: GANDI_TOKEN=\$$(pass show gandi/pat-sandbox) make check-drift"; \
		exit 2; \
	fi
	rm -rf tests/contract/cassettes.new
	mkdir -p tests/contract/cassettes.new
	VCR_CASSETTE_DIR=tests/contract/cassettes.new \
		uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
	uv run python scripts/cassette_drift.py \
		--cassette-dir-old tests/contract/cassettes \
		--cassette-dir-new tests/contract/cassettes.new \
		$(if $(CASSETTE_DRIFT_OPEN_ISSUE),--open-issue,)
