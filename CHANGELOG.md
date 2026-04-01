# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## v2.1.0 (2026-04-01)

### Added
- O(1) tree detection (`|E| = |V| - 1`) that bypasses the entire heavy computation pipeline (ego-network construction, 1000 random network generations, R1/R2 threshold computation) for tree-structured networks. Edges are classified directly as SINK (degree-1) or GLOBAL BRIDGE (all others).

### Fixed
- Incorrect BOND classification on tree networks, where R1 = 0 and all overlaps = 0 caused `0 >= 0` to misclassify every non-SINK edge as BOND. The tree fast-path resolves this while preserving identical results for all 16 benchmark networks.

## v2.0.1 (2026-03-10)

Code quality and robustness improvements.

### Fixed
- Removed unused imports across multiple modules (engine.py, excel_writer.py, main_window.py, suite_experiment_tab.py)
- Removed dead code block in `PlotCanvas.update_figure()` (plot_canvas.py)
- Added error handling for corrupted fingerprint JSON files (`_load_fingerprints`)
- Added `OSError` handling for pickle cache writes, fingerprint JSON saves, and Pajek result file writes
- Added `PowerIterationFailedConvergence` fallback in PageRank plot (uniform weight when convergence fails)
- Fixed GitHub URLs in README.md and pyproject.toml (replaced placeholder with actual repository URL)

## v2.0.0 (2026-01-01)

Complete rewrite from Python 2.7 to Python 3.

### Added
- PySide6 graphical user interface with real-time progress display
- Command-line interface with `analyze` and `suite` subcommands
- Parallel random network generation via `ProcessPoolExecutor`
- Pickle-based caching for random networks and convergence statistics
- Excel output for analysis results and suite experiments
- Network fingerprint JSON storage with correlation table and per-network statistics
- Multi-format network file support: Pajek (.net), GML, GraphML, edge list, adjacency list
- CSV edge classification export for Gephi/Cytoscape interoperability
- Edge type legend on network visualization plots
- Degree distribution plot (histogram + log-log)
- Suite experiment chart titles include suite name
- Suite experiment Excel: network statistics summary sheet (nodes, edges, diameter, etc.)
- Suite experiment Excel/chart: fingerprints sorted by hierarchical clustering order
- Node degree and SINK count columns in Excel node information sheet
- Final edge type column in Excel target network sheet
- Comprehensive error handling: cache corruption recovery, parallel fallback, color index safety, division-by-zero guards
- `RuntimeWarning` when degree-preserving edge swap fails
- Connected components sorted by size (largest = component 1)
- Detailed algorithm documentation in source code

### Changed
- All global variables replaced with explicit function parameters
- Progress reporting via callbacks (supports both GUI and CLI)
- Modern Python APIs: `nx.Graph.nodes` instead of `nx.Graph.node`, `range` instead of `xrange`, f-strings, dataclasses, type hints
- Fixed `network_clustering` SINK endpoint removal (py2 had unreachable branch)
- Fixed node size computation when average information gain is zero

## v1.0.0 (2012)

Original implementation by Chung-Yuan Huang.

- Core algorithm: hierarchical ego-network edge type analysis
- Four edge types: BOND, SINK, LOCAL BRIDGE, GLOBAL BRIDGE
- Statistical adaptive thresholds from random null models
- Suite experiments for WS and NWS small-world network series
- Pajek (.net) file I/O
- Matplotlib visualization
