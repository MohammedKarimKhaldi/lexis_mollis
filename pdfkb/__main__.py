import os

# Must be set before faiss/torch (sentence-transformers) touch OpenMP: on macOS
# their bundled OpenMP runtimes are two separate copies, which OpenMP aborts on
# by default (segfault during `pdfkb similarity build`, right after the
# sentence-transformers model loads and faiss starts indexing). Mirrors the
# same workaround already used in scripts/rag_ask.py -- this just applies it to
# the actual `python -m pdfkb similarity build` entrypoint too. Must happen
# before `from .cli import main`, since that import chain is what eventually
# pulls in faiss/torch.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from .cli import main

raise SystemExit(main())
