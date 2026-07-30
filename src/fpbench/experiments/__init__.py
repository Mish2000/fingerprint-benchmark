"""Reproducible entry points for the experiments this project actually runs.

The application layer, and the only package allowed to know both what an
experiment *is* and what an algorithm *is*: that SD300A is 500 ppi, that the
protocol yields 6,000 comparisons, that a SourceAFIS bundle holds a jar. Those
facts have to live somewhere, and the alternative — letting them leak into the
planner or the runner — is exactly the algorithm-specific branching
docs/adr/0007 exists to prevent.

Dependency rule: ``experiments`` may import everything (``datasets``,
``protocols``, ``adapters``, ``provenance``, ``execution``, ``storage``).
Nothing imports ``experiments``. It changes no other package's rules, and
deleting it would leave the harness intact and unusable — which is the correct
shape for a layer that only composes.
"""

__all__: list[str] = []
