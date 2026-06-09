"""Allows `python3 -m prat` as an alternative to the `prat` CLI command."""
import sys

from .cli import main

sys.exit(main())
