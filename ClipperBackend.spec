import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()  # noqa: F821
packages = ["faster_whisper", "ctranslate2", "tokenizers", "mediapipe", "cv2"]
datas, binaries, hiddenimports = [], [], []
for package in packages:
    try:
        package_data, package_binaries, package_hidden = collect_all(package)
        datas += package_data
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception as error:
        print(f"[clipper spec] collect_all({package}) failed: {error}")

hiddenimports += [
    "backend.main", "backend.durable_pipeline", "backend.routes.pipeline",
    "backend.routes.clips", "backend.routes.clip_room", "backend.routes.edit",
    "backend.routes.editor_v2", "backend.routes.reviews", "backend.routes.profile",
    "backend.routes.settings", "backend.routes.status", "backend.routes.stream",
    "backend.routes.tester", "modules.fetcher.fetcher", "modules.listener.listener",
    "modules.clip_judge", "modules.tester_gateway", "modules.tester_profile",
    "modules.cutter.cutter", "modules.candidate_budget", "modules.pipeline_sync",
    "modules.clip_room", "modules.clip_preview", "modules.clip_reviews",
    "modules.editor", "modules.editor_v2", "modules.profiler.profiler",
    "modules.quality_classifier.classifier", "utils.audio_utils", "utils.whisper_utils",
]
datas += [(str(ROOT / "config" / "settings.json"), "config")]
datas += [(str(ROOT / "db" / "migrations"), "db/migrations")]

# Pre-bundled Whisper model so a clean-machine first run doesn't silently
# download the model. Run `python scripts/fetch_whisper_model.py` first. The
# fail-closed decision (validate model.bin size, only the configured model,
# bypass only on a truthy opt-out) lives in a UNIT-TESTED helper so both the
# success and failure paths are covered (tests/test_whisper_bundle.py).
sys.path.insert(0, str(ROOT))
try:
    from config import cfg as _cfg
    _size = _cfg.whisper.model_size
except Exception as _e:  # noqa: BLE001
    _size = None
    print(f"[clipper spec] WARNING: could not read configured whisper size: {_e}")
from utils.whisper_bundle import plan_whisper_bundle
_plan = plan_whisper_bundle(ROOT / "models", _size,
                            os.environ.get("INSTACLIP_ALLOW_UNBUNDLED_MODEL"))
print(f"[clipper spec] whisper bundle: {_plan['reason']}")
if not _plan["ok"]:
    raise SystemExit("[clipper spec] " + _plan["reason"]
                     + " Or set INSTACLIP_ALLOW_UNBUNDLED_MODEL=1 to build without it.")
datas += _plan["datas"]

analysis = Analysis(
    [str(ROOT / "backend_sidecar.py")],
    pathex=[str(ROOT)], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[], excludes=[
        "pytest", "IPython", "jupyter", "notebook", "tensorboard", "dask", "tornado",
        "torch", "resemblyzer", "discord", "anthropic", "google.genai", "matplotlib",
        "sklearn.tests", "scipy.tests", "alembic.testing", "sqlalchemy.testing",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="instaclip-backend", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
