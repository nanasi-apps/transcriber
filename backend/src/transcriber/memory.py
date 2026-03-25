from __future__ import annotations

import gc

import torch


def release_torch_memory(*, clear_cache: bool = True) -> None:
    gc.collect()

    if not clear_cache:
        return

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        mps = getattr(torch, "mps", None)
        if mps is not None and hasattr(mps, "empty_cache"):
            mps.empty_cache()
