.PHONY: test bench demo install clean
test:        ## run the full suite (engine + core + apps + bench)
	python3 -m pytest knotstore/test_knotstore.py test_knotcore.py apps bench -q
bench:       ## regenerate benchmark results
	python3 -m bench.run
demo:        ## run every app's zero-config demo
	PYTHONPATH=apps/knot python3 -m knot demo --all
install:     ## install the suite as console commands
	./install.sh
clean:       ## remove caches and local app stores
	rm -rf .knotvault .prefixforge .driftledger .checkpointtime bench/results.json bench/RESULTS.md
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
