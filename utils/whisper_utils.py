import ctypes
import logging
import os

from config import cfg
from faster_whisper import WhisperModel

_WINDOWS_CUDA_LIBS = (
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn64_9.dll",
)

_GPU_ONLY_COMPUTE_TYPES = {
    "float16": "int8",
    "int8_float16": "int8",
}

_CUDA_ERROR_MARKERS = (
    "cublas",
    "cudnn",
    "cudart",
    "cuda",
    "cufft",
    "curand",
    "cusolver",
)


def _is_cuda_runtime_error(exc):
    message = str(exc).lower()
    return any(marker in message for marker in _CUDA_ERROR_MARKERS)


def resolve_model_source(size: str):
    """Decide what to hand faster-whisper's WhisperModel for a given size.

    Returns (model_source, download_root):
      * If a model was pre-bundled in the installer, model_source is that local
        DIRECTORY path (faster-whisper loads it in place — no network, no wait),
        and download_root is None.
      * Otherwise model_source is the size NAME (faster-whisper downloads it),
        with download_root pointing inside the app's own data dir so the one-time
        download is cached locally instead of in the roaming HuggingFace cache.

    This is what makes a clean-machine first run instant when the model ships in
    the installer, while still working if it doesn't.
    """
    from config import paths
    bundled = paths.bundled_whisper_dir(size)
    if (bundled / "model.bin").exists():
        return str(bundled), None
    try:
        paths.WHISPER_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return size, None
    return size, str(paths.WHISPER_DOWNLOAD_DIR)


def _missing_windows_cuda_libs():
    missing = []
    for lib_name in _WINDOWS_CUDA_LIBS:
        try:
            ctypes.WinDLL(lib_name)
        except OSError:
            missing.append(lib_name)
    return missing


class ManagedWhisperModel:
    def __init__(self, logger=None):
        self.log = logger or logging.getLogger("whisper")
        self.model_size = cfg.whisper.model_size
        self.preferred_device = cfg.whisper.device
        self.preferred_compute_type = cfg.whisper.compute_type
        self.active_device = None
        self.active_compute_type = None
        self._model = None

    def _compute_type_for(self, device):
        if device == "cpu":
            return _GPU_ONLY_COMPUTE_TYPES.get(
                self.preferred_compute_type,
                self.preferred_compute_type,
            )
        return self.preferred_compute_type

    def _load_model(self, device, reason=None):
        compute_type = self._compute_type_for(device)

        if reason:
            self.log.warning(reason)

        if device == "cpu" and compute_type != self.preferred_compute_type:
            self.log.warning(
                "Switching compute_type from '%s' to '%s' for CPU compatibility.",
                self.preferred_compute_type,
                compute_type,
            )

        model_source, download_root = resolve_model_source(self.model_size)
        if download_root is None and model_source != self.model_size:
            self.log.info("Loading pre-bundled Whisper '%s' on %s (no download)...", self.model_size, device)
        else:
            self.log.info("Loading Whisper '%s' on %s...", self.model_size, device)
        self._model = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
        self.active_device = device
        self.active_compute_type = compute_type
        self.log.info("Whisper ready on %s.", device)
        return self

    def ensure_loaded(self):
        if self._model is not None:
            return self

        requested_device = self.preferred_device

        if requested_device == "cuda" and os.name == "nt":
            missing = _missing_windows_cuda_libs()
            if missing:
                missing_list = ", ".join(missing)
                reason = (
                    "CUDA was requested, but required NVIDIA runtime libraries "
                    f"are missing or unavailable ({missing_list}). Falling back to CPU."
                )
                return self._load_model("cpu", reason=reason)

        try:
            return self._load_model(requested_device)
        except Exception as exc:
            if requested_device == "cuda" and _is_cuda_runtime_error(exc):
                reason = (
                    "CUDA Whisper initialization failed "
                    f"({exc}). Falling back to CPU."
                )
                return self._load_model("cpu", reason=reason)
            raise

    def transcribe(self, *args, **kwargs):
        self.ensure_loaded()

        try:
            return self._model.transcribe(*args, **kwargs)
        except Exception as exc:
            if self.active_device == "cuda" and _is_cuda_runtime_error(exc):
                reason = (
                    "CUDA transcription failed "
                    f"({exc}). Retrying once on CPU."
                )
                self._load_model("cpu", reason=reason)
                return self._model.transcribe(*args, **kwargs)
            raise


def load_whisper_model(logger=None):
    return ManagedWhisperModel(logger=logger).ensure_loaded()
