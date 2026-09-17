from __future__ import annotations

import logging
import shutil
import subprocess
import time

from mt_linux.config import ProtocolConfig

logger = logging.getLogger(__name__)

# How long to wait (seconds) for ollama to become responsive after launch.
_LAUNCH_TIMEOUT = 120

# Poll interval (seconds) when waiting for the endpoint.
_READINESS_INTERVAL = 2


def _parse_endpoint_port(endpoint: str) -> int:
    """Extract the port number from an Ollama-compatible endpoint URL."""
    # Default port when not explicitly specified.
    if ":" not in endpoint.replace("http://", "").replace("https://", "").split("/")[0]:
        return 11434
    host_part = endpoint.replace("http://", "").replace("https://", "").split("/")[0]
    return int(host_part.rsplit(":", 1)[1])


def _check_endpoint(endpoint: str) -> bool:
    """Return True if the Ollama API responds to a health/status probe."""
    try:
        import httpx
    except ImportError:
        # Fallback: try connecting to the port via subprocess.
        port = _parse_endpoint_port(endpoint)
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://localhost:{port}/"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip() in ("200", "404")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    try:
        r = httpx.get(endpoint.rsplit("/", 2)[0] + "/", timeout=5)
        # 200 = healthy, 404 is fine (the root path may not exist but the server is up).
        return r.status_code in (200, 404)
    except Exception:
        return False


def _ensure_model_available(endpoint: str, model: str) -> None:
    """Pull the model via the ollama CLI if it is not already present."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and model in result.stdout:
            return  # Already present.
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    logger.info("Pulling Ollama model '%s' ...", model)
    try:
        subprocess.run(
            ["ollama", "pull", model],
            check=True,
            timeout=600,
        )
        logger.info("Model '%s' ready.", model)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        logger.warning("Failed to pull model '%s': %s", model, exc)


def normalize_model_name(model: str) -> str:
    """Return a canonical ollama model name, adding the ``:latest`` tag when missing."""
    if not model or ":" in model:
        return model
    return f"{model}:latest"


def unload_ollama_model(model: str) -> bool:
    """Ask ollama to unload the given model from GPU memory.

    Tries the configured name and common tag variants, because ollama
    registers models with a tag (e.g. ``llama3.1:latest``) while configs
    often omit the tag (``llama3.1``).  Returns True if any stop call
    succeeded (exit code 0), False otherwise.  Non-fatal: callers may
    log and continue.
    """
    if not model:
        return False
    candidates = [model]
    normalized = normalize_model_name(model)
    if normalized not in candidates:
        candidates.append(normalized)
    for name in candidates:
        try:
            result = subprocess.run(
                ["ollama", "stop", name],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                logger.info("Unloaded ollama model '%s'", name)
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.debug("Failed to unload ollama model '%s' (non-fatal)", name)
    return False


def ensure_ollama_ready(config: ProtocolConfig) -> None:
    """Block until the Ollama endpoint is responsive; launch it if needed."""
    if not config.enabled:
        return

    # Fast path: endpoint is already up.
    if _check_endpoint(config.endpoint):
        _ensure_model_available(config.endpoint, config.model)
        return

    # Try to launch ollama in the background.
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        raise RuntimeError(
            "ollama binary not found on PATH. Install Ollama or disable protocol generation."
        )

    logger.info("Starting ollama serve ...")
    subprocess.Popen(
        [ollama_bin, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + _LAUNCH_TIMEOUT
    while time.monotonic() < deadline:
        if _check_endpoint(config.endpoint):
            _ensure_model_available(config.endpoint, config.model)
            return
        time.sleep(_READINESS_INTERVAL)

    raise RuntimeError(
        f"ollama did not become ready within {_LAUNCH_TIMEOUT}s. "
        "Check that the endpoint URL is correct and that ollama can start."
    )
