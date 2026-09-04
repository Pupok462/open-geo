"""Iterative, visual SEO semantic kernel on top of demand/.

Paste a URL, collect a batch of real questions, accept/reject (or auto),
grow the lattice. Volume comes from demand/ when a ruler is configured;
otherwise suggest proves the phrasing is real and says so.
"""

from kernel.schema import Kernel, Question

__all__ = ["Kernel", "Question"]
