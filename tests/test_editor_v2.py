from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import editor_v2


class EditorV2Tests(unittest.TestCase):
    def test_timeline_thumbnail_is_timestamped_quantized_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.touch()

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"jpeg")
                return SimpleNamespace(returncode=0, stderr=b"")

            with (
                patch.object(editor_v2.paths, "DATA_DIR", Path(tmp)),
                patch.object(editor_v2.editor, "media_kind", return_value="video"),
                patch.object(editor_v2.editor, "probe", return_value={"duration": 10}),
                patch.object(editor_v2.subprocess, "run", side_effect=fake_run) as run,
            ):
                first = editor_v2.timeline_thumbnail_for(source, "fingerprint", 3.24, 180)
                second = editor_v2.timeline_thumbnail_for(source, "fingerprint", 3.20, 180)
            self.assertEqual(first, second)
            self.assertTrue(first.exists())
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertIn("3.000", command)

    def test_project_save_load_is_atomic_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            project = {
                "schemaVersion": 2,
                "id": "prj_test",
                "name": "Test",
                "revision": 1,
                "createdAt": 1,
                "updatedAt": 1,
                "assets": {},
                "tracks": [],
                "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
            }
            with patch.object(editor_v2.paths, "EDITOR_PROJECTS_DIR", project_dir):
                editor_v2.save_project(project)
                restored = editor_v2.load_project("prj_test")
            self.assertEqual(restored["name"], "Test")
            self.assertFalse((project_dir / "prj_test.json.tmp").exists())

    def test_local_landscape_vod_creates_in_place_youtube_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Rocomamas Challenge Full Vod.mp4"
            source.touch()
            asset = {
                "id": "vod", "kind": "video", "origin": "local-vod",
                "name": source.name, "duration": 1191.4, "width": 1920,
                "height": 1080, "hasAudio": True, "fingerprint": "test",
            }
            with (
                patch.object(editor_v2.editor, "media_kind", return_value="video"),
                patch.object(editor_v2.editor, "probe", return_value={"duration": 1191.4, "width": 1920, "height": 1080, "fps": 60, "has_audio": True}),
                patch.object(editor_v2, "list_projects", return_value=[]),
                patch.object(editor_v2, "asset_from_path", return_value=asset.copy()),
                patch.object(editor_v2, "save_project", side_effect=lambda project: project),
            ):
                project = editor_v2.create_project_from_local(str(source))
            self.assertEqual(project["canvas"], {"width": 1920, "height": 1080, "fps": 30, "background": "#000000"})
            self.assertEqual(project["export"]["width"], 1920)
            self.assertEqual(project["assets"]["vod"]["path"], str(source.resolve()))
            self.assertTrue(any(track["kind"] == "caption" for track in project["tracks"]))

    def test_render_command_layers_visuals_and_overlapping_audio(self):
        project = {
            "schemaVersion": 2,
            "id": "prj_render",
            "name": "Render",
            "assets": {
                "video": {"id": "video", "kind": "video", "hasAudio": True},
                "boom": {"id": "boom", "kind": "audio", "hasAudio": True},
            },
            "tracks": [
                {"id": "v1", "kind": "video", "name": "V1", "order": 0, "hidden": False, "muted": False, "solo": False, "locked": False, "items": [{
                    "id": "clip", "assetId": "video", "trackId": "v1", "timelineStart": 0,
                    "sourceIn": 0, "sourceOut": 5, "speed": 1, "enabled": True,
                    "video": {"x": 0, "y": 0, "width": 1080, "height": 1920, "rotation": 0, "opacity": 1, "crop": None, "fit": "contain"},
                    "audio": {"volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False},
                }]},
                {"id": "a1", "kind": "audio", "name": "A1", "order": 10, "hidden": False, "muted": False, "solo": False, "locked": False, "items": [
                    {"id": "boom1", "assetId": "boom", "trackId": "a1", "timelineStart": 1, "sourceIn": 0, "sourceOut": 2, "speed": 1, "enabled": True, "audio": {"volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False}},
                    {"id": "boom2", "assetId": "boom", "trackId": "a1", "timelineStart": 1, "sourceIn": 0, "sourceOut": 2, "speed": 1, "enabled": True, "audio": {"volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False}},
                ]},
            ],
            "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
            "export": {"outputName": "test", "width": 1080, "height": 1920, "fps": 30, "quality": "draft", "range": "full"},
        }
        command = editor_v2.build_render_command(
            project,
            Path("out.mp4"),
            resolver=lambda _project, asset_id: Path(f"{asset_id}.mp4"),
        )
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("overlay=", filters)
        self.assertIn("amix=inputs=3", filters)
        self.assertEqual(command.count("-i"), 3)
        self.assertEqual(command.count("-ss"), 3)
        self.assertIn("trim=start=0.000000:end=5.000000", filters)
        self.assertIn("atrim=start=0.000000:end=2.000000", filters)

        project["tracks"][0]["items"][0]["video"]["blur"] = 28
        blurred = editor_v2.build_render_command(
            project,
            Path("blurred.mp4"),
            resolver=lambda _project, asset_id: Path(f"{asset_id}.mp4"),
        )
        blur_filters = blurred[blurred.index("-filter_complex") + 1]
        self.assertIn("boxblur=28.0000", blur_filters)

    def test_stale_project_save_cannot_overwrite_newer_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            base = {
                "schemaVersion": 2, "id": "prj_stale", "name": "Test",
                "revision": 2, "createdAt": 1, "updatedAt": 1,
                "assets": {}, "tracks": [],
                "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
            }
            with patch.object(editor_v2.paths, "EDITOR_PROJECTS_DIR", project_dir):
                editor_v2.save_project(base)
                stale = {**base, "revision": 1}
                with self.assertRaisesRegex(ValueError, "stale project revision"):
                    editor_v2.save_project(stale)

    def test_render_command_includes_captions_and_transitions(self):
        project = {
            "schemaVersion": 2, "id": "prj_youtube", "name": "YouTube",
            "assets": {
                "video": {"id": "video", "kind": "video", "hasAudio": True},
                "caption": {"id": "caption", "kind": "caption", "hasAudio": False},
            },
            "tracks": [
                {"id": "v1", "kind": "video", "name": "V1", "order": 0, "hidden": False, "muted": False, "solo": False, "locked": False, "items": [
                    {"id": "outgoing", "assetId": "video", "trackId": "v1", "timelineStart": 0, "sourceIn": 0, "sourceOut": 5, "speed": 1, "enabled": True, "video": {"x": 0, "y": 0, "width": 1920, "height": 1080, "rotation": 0, "opacity": 1, "crop": None, "fit": "contain"}, "audio": {"volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False}},
                    {"id": "incoming", "assetId": "video", "trackId": "v1", "timelineStart": 5, "sourceIn": 5, "sourceOut": 10, "speed": 1, "enabled": True, "video": {"x": 0, "y": 0, "width": 1920, "height": 1080, "rotation": 0, "opacity": 1, "crop": None, "fit": "contain"}, "audio": {"volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False}},
                ]},
                {"id": "c1", "kind": "caption", "name": "C1", "order": 20, "hidden": False, "muted": False, "solo": False, "locked": False, "items": [
                    {"id": "cap1", "assetId": "caption", "trackId": "c1", "timelineStart": 1, "sourceIn": 0, "sourceOut": 3, "speed": 1, "enabled": True, "caption": {"text": "Roco: let's go!", "fontSize": 72, "color": "#ffffff", "backgroundColor": "#000000", "backgroundOpacity": 0.5, "strokeColor": "#000000", "strokeWidth": 3, "position": "bottom", "bold": True, "variant": "title", "animation": "fade"}},
                ]},
            ],
            "transitions": [{"id": "trn", "fromItemId": "outgoing", "toItemId": "incoming", "kind": "fade_white", "duration": 0.8}],
            "canvas": {"width": 1920, "height": 1080, "fps": 30, "background": "#000000"},
            "export": {"outputName": "youtube", "width": 1920, "height": 1080, "fps": 30, "quality": "draft", "range": "full"},
        }
        command = editor_v2.build_render_command(
            project, Path("youtube.mp4"),
            resolver=lambda _project, asset_id: Path(f"{asset_id}.mp4"),
        )
        filters = command[command.index("-filter_complex") + 1]
        self.assertEqual(command.count("-i"), 2)
        self.assertIn("color=white", filters)
        self.assertIn("drawtext=text='Roco\\: let\u2019s go!'", filters)
        self.assertIn(":alpha='if(lt(t\\,1.350000)", filters)
        self.assertIn(r"enable=between(t\,1.000000\,4.000000),null", filters)

        project["transitions"][0]["kind"] = "mix"
        mixed = editor_v2.build_render_command(
            project, Path("mix.mp4"),
            resolver=lambda _project, asset_id: Path(f"{asset_id}.mp4"),
        )
        mix_filters = mixed[mixed.index("-filter_complex") + 1]
        self.assertIn("alpha=1", mix_filters)

    def test_sound_bin_mp4_is_normalized_to_audio(self):
        project = {
            "schemaVersion": 2,
            "id": "prj_sound_kind",
            "assets": {
                "boom": {
                    "id": "boom", "kind": "video", "origin": "sound-bin",
                    "name": "boom.mp4", "hasAudio": False,
                },
            },
            "tracks": [],
        }
        editor_v2.validate_project(project)
        self.assertEqual(project["assets"]["boom"]["kind"], "audio")
        self.assertTrue(project["assets"]["boom"]["hasAudio"])

    def test_video_proxy_is_cached_and_keeps_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(b"proxy")
                return type("Result", (), {"returncode": 0, "stderr": b""})()

            with (
                patch.object(editor_v2.paths, "EDITOR_VIDEO_PROXIES_DIR", root / "proxies"),
                patch.object(editor_v2.subprocess, "run", side_effect=fake_run),
            ):
                first = editor_v2.video_proxy_for(source, "fingerprint")
                second = editor_v2.video_proxy_for(source, "fingerprint")
            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), b"proxy")
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(len(commands), 1)
            self.assertIn("+faststart", commands[0])

    def test_render_project_uses_filter_script_for_windows_safe_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observed = {}

            def fake_run(command, **_kwargs):
                observed["command"] = command
                script = Path(command[command.index("-filter_complex_script") + 1])
                observed["filter"] = script.read_text(encoding="utf-8")
                (root / "long_captions.mp4").write_bytes(b"rendered")
                return type("Result", (), {"returncode": 0, "stderr": b""})()

            command = [
                "ffmpeg", "-y", "-i", "source.mp4", "-filter_complex", "[0:v]null[vout];anullsrc[aout]",
                "-map", "[vout]", "-map", "[aout]", str(root / "ignored.mp4"),
            ]
            project = {"name": "Long captions", "export": {"outputName": "long_captions"}}
            with (
                patch.object(editor_v2.editor, "EDITED_DIR", root),
                patch.object(editor_v2, "build_render_command", return_value=command),
                patch.object(editor_v2.subprocess, "run", side_effect=fake_run),
            ):
                output = editor_v2.render_project(project)
            self.assertEqual(output.read_bytes(), b"rendered")
            self.assertIn("-filter_complex_script", observed["command"])
            self.assertNotIn("-filter_complex", observed["command"])
            self.assertEqual(observed["filter"], "[0:v]null[vout];anullsrc[aout]")
            self.assertFalse((root / "long_captions.filters.txt").exists())

    def test_create_project_from_legacy_spec_includes_sound_fx_and_audio_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "clip.mp4"
            source.touch()
            sound = root / "boom.mp4"
            sound.touch()

            spec = {
                "bucket": "output",
                "stem": "clip1",
                "trim": {"start": 1.0, "end": 6.0},
                "crop": [10, 20, 100, 200],
                "audio_normalize": True,
                "audio_boost_db": 6.0,
                "sound_fx": [{"name": "boom", "at": 2.0, "gain": 0.8}],
            }

            with (
                patch.object(editor_v2, "resolve_clip", return_value=source),
                patch.object(editor_v2.editor, "sound_path", return_value=sound),
                patch.object(editor_v2.editor, "media_kind", return_value="video"),
                patch.object(editor_v2.editor, "probe", return_value={"duration": 10.0, "width": 1080, "height": 1920, "fps": 30, "has_audio": True}),
                patch.object(editor_v2.paths, "EDITOR_PROJECTS_DIR", root),
            ):
                project = editor_v2.create_project_from_legacy_spec(spec)

            v_track = next(t for t in project["tracks"] if t["kind"] == "video")
            v_item = v_track["items"][0]
            self.assertEqual(v_item["sourceIn"], 1.0)
            self.assertEqual(v_item["sourceOut"], 6.0)
            self.assertEqual(v_item["video"]["crop"], [10, 20, 100, 200])
            self.assertTrue(v_item["audio"]["normalize"])

            a_track = next(t for t in project["tracks"] if t["kind"] == "audio")
            sound_item = a_track["items"][0]
            self.assertEqual(sound_item["timelineStart"], 2.0)
            self.assertEqual(sound_item["audio"]["volume"], 0.8)


if __name__ == "__main__":
    unittest.main()
