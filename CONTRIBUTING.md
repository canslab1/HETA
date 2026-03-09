# Contributing to HETA

Thank you for your interest in contributing to HETA! This document provides guidelines for contributing to this project.

## How to Contribute

### Reporting Issues

- Use the [GitHub Issues](https://github.com/canslab1/HETA/issues) page to report bugs or request features.
- When reporting a bug, please include:
  - Python version (`python --version`)
  - Operating system
  - Steps to reproduce the issue
  - Expected vs. actual behavior
  - Relevant error messages or screenshots

### Submitting Changes

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/HETA.git
   cd HETA
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Make your changes** and test them.
5. **Commit** with a clear message:
   ```bash
   git commit -m "Add: brief description of your change"
   ```
6. **Push** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
7. Open a **Pull Request** on GitHub.

## Development Setup

```bash
git clone https://github.com/canslab1/HETA.git
cd HETA
pip install -r requirements.txt
python run_heta.py  # Verify the GUI launches correctly
```

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- Use type hints where practical.
- Keep functions focused and reasonably sized.
- Document non-obvious algorithms with comments referencing the paper.

## Project Architecture

| Module | Responsibility |
|--------|---------------|
| `heta/engine.py` | Core HETA algorithm (5-phase edge classification) |
| `heta/cli.py` | Command-line interface |
| `heta/plotting.py` | Matplotlib visualizations |
| `heta/excel_writer.py` | Excel and CSV output |
| `heta/constants.py` | Configuration constants and datasets |
| `heta/gui/` | PySide6 graphical interface |

## Questions?

Feel free to open an issue for any questions about the codebase or contribution process.
