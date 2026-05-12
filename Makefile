# Developer-facing make targets. CI doesn't use these — CI uses `uv run pytest`
# and `uv run python scripts/check_coverage_thresholds.py` directly.

.PHONY: help refresh-cassettes check-cassettes-fresh

help:
	@echo "Targets:"
	@echo "  refresh-cassettes      Re-record every contract cassette against api.gandi.net."
	@echo "                         Requires GANDI_TOKEN in env (use \`pass show gandi/pat-sandbox\`)."
	@echo "  check-cassettes-fresh  Fail if any cassette is older than 180 days."

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
