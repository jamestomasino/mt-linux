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
