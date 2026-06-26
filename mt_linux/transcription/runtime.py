from __future__ import annotations


def cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def preferred_torch_device():
    import torch

    return torch.device("cuda" if cuda_available() else "cpu")


def resolve_device(requested: str) -> str:
    normalized = requested.strip().lower()
    if normalized in {"", "auto"}:
        return "cuda" if cuda_available() else "cpu"
    return normalized


def gpu_ready(min_free_mb: int = 4096) -> bool:
    """Check whether the GPU has enough free memory to process a job.

    Returns True immediately if CUDA is not available (CPU path).
    When CUDA is present, probes free memory and returns False if
    another process (e.g. LM Studio) has consumed too much.
    """
    try:
        import torch
    except ImportError:
        return True  # No torch -> CPU path, always "ready"

    if not torch.cuda.is_available():
        return True

    try:
        free, _ = torch.cuda.mem_get_info()  # bytes
        free_mb = free / (1024 * 1024)
        if free_mb < min_free_mb:
            return False
        return True
    except Exception:
        # If we can't query, assume ready and let downstream handle OOM
        return True
