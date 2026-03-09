# HETA — Hierarchical Edge Type Analysis

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green)

**HETA** is a topology-driven tool for classifying every edge in a complex network into one of four structural types, without requiring any pre-defined community labels or edge weights.

```
BOND            ─── Redundant intra-community link
SINK (Silk)     ─── Pendant link with a degree-1 endpoint
LOCAL BRIDGE    ─── Inter-cluster connection between nearby communities
GLOBAL BRIDGE   ─── Long-range connection between distant communities
```

## Overview

In complex networks, not all links serve the same structural role. Some reinforce tight-knit communities, while others bridge distant clusters. Understanding these roles is essential for community detection, influence propagation analysis, and network resilience studies.

HETA classifies every edge in an undirected network into one of four hierarchical types based purely on topology — no community labels, edge weights, or parameter tuning required. By constructing multi-layer ego networks and comparing neighborhood overlap against a statistical null model, HETA produces a 4D "network fingerprint" that characterizes the structural composition of any network.

## Features

- **Parameter-free** — Classification is driven entirely by network topology; no community count, edge weight, or manual threshold required.
- **Multi-scale analysis** — Ego networks expand layer by layer, capturing both local and global structural information simultaneously.
- **Statistically adaptive thresholds** — The R1 threshold is derived from a degree-preserving random null model (mean + 2&sigma;), automatically adapting to networks of any size and density.
- **Exhaustive & mutually exclusive** — A STOP/PASS state machine guarantees every edge is classified into exactly one type.
- **Network fingerprint** — The proportions of the four edge types form a 4D feature vector for cross-network comparison and hierarchical clustering.
- **Multi-format input** — Supports Pajek (.net), GML, GraphML, edge list, and adjacency list formats.
- **Dual interface** — Both a PySide6 GUI and a full-featured CLI.
- **Parallel processing** — Random network generation can use multiple CPU cores.
- **Caching** — Intermediate results are cached to disk, avoiding redundant computation on re-runs.
- **Rich output** — Excel workbooks, CSV edge classification tables (Gephi/Cytoscape compatible), and multiple plot types (network, degree distribution, betweenness, PageRank, clustering).

## Installation

```bash
git clone https://github.com/canslab1/HETA.git
cd HETA
pip install -r requirements.txt
```

### Dependencies

| Package | Version |
|---------|---------|
| networkx | &ge; 3.0 |
| numpy | &ge; 1.24 |
| scipy | &ge; 1.10 |
| matplotlib | &ge; 3.7 |
| openpyxl | &ge; 3.1 |
| PySide6 | &ge; 6.5 |

> PySide6 is only required for the GUI. CLI-only usage works without it.

## Quick Start

### GUI Mode

```bash
python run_heta.py
```

### CLI Mode

```bash
# Analyze a single network
python run_heta.py analyze -i nets/karate.net

# Analyze with parallel random network generation (faster)
python run_heta.py analyze -i nets/karate.net -p

# Run the DEMO suite experiment
python run_heta.py suite --name DEMO --run
```

## CLI Reference

### `analyze` — Single Network Analysis

```
python run_heta.py analyze -i <file> [options]

Options:
  -i, --input FILE        Path to network file (required)
                          Supported: .net .gml .graphml .edgelist .edges .adjlist
  -t, --times N           Number of random networks for null model (default: 1000)
  -q, --quick LAYERS      Quick mode: limit ego-network expansion to N layers
  -p, --parallel          Enable parallel random network generation
  -w, --workers N         Number of parallel workers (default: CPU cores - 1)
  -d, --debug             Print debug messages
  --show-detail           Save per-layer detail plots
  --show-betweenness      Save betweenness centrality plot
  --show-pagerank         Save PageRank distribution plot
  --show-clustering       Save clustering coefficient plot
  --show-degree           Save degree distribution plot
  --export-csv            Export edge classification as CSV (for Gephi/Cytoscape)
```

### `suite` — Batch Suite Experiment

```
python run_heta.py suite --name <SUITE> [options]

Options:
  --name {DEMO,WS_SWN,NWS_SWN}   Suite name (default: DEMO)
  --run                            Run analysis first; omit to view existing results
  --dir DIR                        Directory containing network files (default: .)
  -t, --times N                    Number of random networks (default: 1000)
  -d, --debug                      Print debug messages
```

## Sample Networks

HETA ships with three sets of sample networks:

### DEMO (16 networks)

Classic benchmark networks from the literature:

| Network | Nodes | Description |
|---------|-------|-------------|
| karate | 34 | Zachary's karate club |
| dolphins | 62 | Bottlenose dolphin social network |
| football | 115 | American college football |
| jazz | 198 | Jazz musician collaborations |
| celegans | 297 | C. elegans neural network |
| lesmis | 77 | Les Mis&eacute;rables character co-occurrences |
| florentine | 15 | Florentine families marriage network |
| and 9 more... | | |

### WS_SWN (16 networks)

Watts-Strogatz small-world networks with rewiring probability ranging from 0.0 to 1.0.

### NWS_SWN (16 networks)

Newman-Watts-Strogatz small-world networks with the same probability range.

## Algorithm Overview

HETA classifies edges through a five-phase pipeline:

1. **Ego network construction** — For each edge (s, t), build multi-layer ego networks for both endpoints using BFS expansion up to *r* hops. The number of layers *r* is automatically determined from the average shortest path length.

2. **Neighborhood overlap** — For each layer, compute the overlap between the ring neighborhoods of s and t using cross-layer intersection, normalized by the minimum possible overlap. This yields a ratio in [0, 1] for each layer.

3. **Null model threshold (R1)** — Generate degree-preserving random networks and compute the same overlap metric. R1 = mean + 2&sigma; of the random distribution, providing a statistically grounded boundary (roughly the 95th percentile).

4. **Multi-phase classification**
   - **Phase 1 — SINK**: Edges where either endpoint has degree 1.
   - **Phase 2 — BOND vs LOCAL BRIDGE**: Edges with overlap above R1 are BOND (community-internal). Among those below R1, a secondary threshold R2 (mean &minus; 1&sigma; of the bridge overlap distribution) separates LOCAL BRIDGE from candidates for GLOBAL BRIDGE.
   - **Phase 3 — GLOBAL BRIDGE**: All remaining unclassified edges.

5. **Fingerprinting** — Compute the proportion of each edge type to form a 4D network fingerprint, enabling cross-network comparison via correlation and hierarchical clustering.

## Project Structure

```
HETA/
├── run_heta.py              # Unified entry point (GUI / CLI)
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Package metadata
├── heta/
│   ├── __init__.py          # Package init (version, author)
│   ├── engine.py            # Core analysis engine
│   ├── constants.py         # Constants and dataset definitions
│   ├── cli.py               # Command-line interface
│   ├── plotting.py          # Matplotlib visualization
│   ├── excel_writer.py      # Excel output (openpyxl)
│   └── gui/
│       ├── main_window.py   # PySide6 main window
│       ├── link_analysis_tab.py
│       ├── suite_experiment_tab.py
│       ├── plot_canvas.py   # Embedded matplotlib canvas
│       └── worker.py        # Background worker threads
├── nets/                    # DEMO sample networks (Pajek .net)
├── ws_swn/                  # Watts-Strogatz suite networks
└── nws_swn/                 # Newman-Watts-Strogatz suite networks
```

## Output

For each analyzed network component, HETA produces:

| File | Description |
|------|-------------|
| `*_result.net` | Pajek file with edge classifications |
| `*_result.png` | Network visualization colored by edge type (with legend) |
| `*_result.xlsx` | Detailed results: edge data, random networks, node information |
| `*_edges.csv` | Edge classification CSV (with `--export-csv`), importable by Gephi/Cytoscape |

Optional plots (enabled by `--show-*` flags): degree distribution, betweenness centrality, PageRank, clustering, per-layer detail.

Suite experiments additionally produce:

| File | Description |
|------|-------------|
| `fingerprints_*.png` | Stacked bar chart of edge type proportions |
| `correlation_*.png` | Fingerprint correlation heatmap |
| `hierarchy_*.png` | Hierarchical clustering dendrogram |
| `suite_result_*.xlsx` | Fingerprints, correlation matrix, and network statistics |

## Authors

- **Chung-Yuan Huang** (黃崇源) — Department of Computer Science and Information Engineering, Chang Gung University, Taiwan (gscott@mail.cgu.edu.tw)

Original implementation: March 2012 (Python 2.7); Current version: 2.0 (Python 3, 2026)

## References

1. Huang, C.-Y., Chin, W. C. B., Fu, Y.-H., & Tsai, Y.-S. (2019). Beyond bond links in complex networks: Local bridges, global bridges and silk links. *Physica A: Statistical Mechanics and its Applications*, 536, 121027. https://doi.org/10.1016/j.physa.2019.04.263

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
