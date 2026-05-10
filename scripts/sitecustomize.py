"""sitecustomize: import-time monkey-patches for the AgencyBench harness.

Loaded by Python automatically *if* this directory is on PYTHONPATH (or any
sys.path entry that comes before the venv's site-packages). The driver
exports `PYTHONPATH=/workspace/scripts:$PYTHONPATH` before invoking
eval_task.py so this file is picked up.

Patches:

1. SiiAgentOptions: Backend/scenario1, Backend/scenario2, Backend/scenario3,
   Code/scenario{1,4,5,8,9}, Research/scenario{1,3} all pass an
   `enable_data_upload=False` kwarg that the installed sii-agent-sdk==0.1.5
   does NOT accept (its dataclass only has 11 fields). Without this patch
   every affected scenario fails with `unexpected keyword argument
   'enable_data_upload'` and the agent never starts. Patch turns the
   constructor into a kwargs-tolerant wrapper that silently drops fields
   the dataclass doesn't define.
"""

from __future__ import annotations


def _patch_sii_agent_options() -> None:
    try:
        from sii_agent_sdk import types as _types
    except Exception:
        return
    cls = getattr(_types, "SiiAgentOptions", None)
    if cls is None or getattr(cls, "_agencybench_patched", False):
        return
    import dataclasses

    real_fields = {f.name for f in dataclasses.fields(cls)}
    real_init = cls.__init__

    def __init__(self, *args, **kwargs):  # type: ignore[no-redef]
        unknown = {k: kwargs.pop(k) for k in list(kwargs) if k not in real_fields}
        real_init(self, *args, **kwargs)
        # Stash the dropped values in a side dict in case anything wants
        # them (purely diagnostic — the SDK never reads back).
        if unknown:
            object.__setattr__(self, "_dropped_kwargs", unknown)

    cls.__init__ = __init__  # type: ignore[assignment]
    cls._agencybench_patched = True  # type: ignore[attr-defined]


_patch_sii_agent_options()
