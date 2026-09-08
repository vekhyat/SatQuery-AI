"""Tool 3: georeferenced optical/SAR baseline land-cover fusion."""

from .inputs import BandSource, DatasetError, discover, load_manifest
from .pipeline import Config, check_dataset, run_pipeline
from ._version import __version__
from .contracts import CONTRACT_VERSION, TOOL_NAME, check_tool3_request, optical_sar_v1, prepare_request

__all__ = ["BandSource", "Config", "DatasetError", "check_dataset", "discover", "load_manifest", "run_pipeline",
           "__version__", "CONTRACT_VERSION", "TOOL_NAME", "check_tool3_request", "optical_sar_v1", "prepare_request"]
