CHART_DIR := chart

.PHONY: chart_dependencies chart_update_dependencies chart_lint

# Reproduce the versions recorded in Chart.lock without changing the lock.
chart_dependencies:
	@echo "Building Helm dependencies for $(CHART_DIR)..."
	helm dependency build --skip-refresh $(CHART_DIR)

# Intentionally resolve Chart.yaml again and regenerate Chart.lock.
chart_update_dependencies:
	@echo "Updating Helm dependencies for $(CHART_DIR)..."
	helm dependency update $(CHART_DIR)

chart_lint: chart_dependencies
	@echo "Linting $(CHART_DIR)..."
	helm lint $(CHART_DIR) --with-subcharts
