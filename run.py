#!/usr/bin/env python3
"""
Entry point for the PSO Permit Functional Class Enrichment tool.

Usage (Windows or Linux/macOS):
    python run.py

All configurable behavior (date range, permit types, utilities, API
settings, QGIS fallback switch, output location) lives in config.py -
edit that file, then re-run this script. See README.md for details.
"""

from pso_enrichment.pipeline import run

if __name__ == "__main__":
    run()
