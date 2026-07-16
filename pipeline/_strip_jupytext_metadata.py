"""Strip the raw jupytext metadata cell that MyST does not understand.

Called as a post-processing step after `jupytext --to notebook --execute`,
which leaves a leading raw cell containing the jupytext/kernelspec header.

    uv run python pipeline/_strip_jupytext_metadata.py <notebook.ipynb>
"""

import sys

import nbformat

notebook_path = sys.argv[1]

nb = nbformat.read(notebook_path, as_version=4)
nb.cells = [
    c for c in nb.cells
    if not (c.cell_type == "raw" and "jupytext" in c.source)
]
nbformat.write(nb, notebook_path)
