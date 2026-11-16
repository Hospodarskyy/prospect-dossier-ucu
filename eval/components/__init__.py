"""One module per component of the pipeline; each has evaluate(runs) -> dict."""
from . import (case_selection, judge, memory, request_parsing, researcher, source_verifier,
               system, writer)

# pipeline order
MODULES = {
    "request_parsing": request_parsing,
    "researcher": researcher,
    "source_verifier": source_verifier,
    "judge": judge,
    "writer": writer,
    "case_selection": case_selection,
    "memory": memory,
    "system": system,
}
