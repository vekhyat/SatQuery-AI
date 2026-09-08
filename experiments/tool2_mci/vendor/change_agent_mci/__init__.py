"""Minimal Change-Agent MCI model runtime.

Vendored under the MIT License; see LICENSE.txt and ATTRIBUTION.md.
"""

from pathlib import Path

VOCAB_PATH = Path(__file__).with_name("vocab.json")

__all__ = ["VOCAB_PATH"]

