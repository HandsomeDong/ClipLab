import subprocess

from cliplab_backend.config import Settings
from cliplab_backend.services.watermark import WatermarkService


def test_merge_audio_returns_success_without_warning(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    temp_video = tmp_path / "temp.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source-video")
    temp_video.write_bytes(b"silent-video")

    monkeypatch.setattr(Settings, "resolve_ffmpeg_path", lambda self: "/tmp/fake-ffmpeg")

    def fake_run(command, check, capture_output, text):
        output.write_bytes(b"merged-video")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WatermarkService()._merge_audio(source, temp_video, output)

    assert result.audio_merged is True
    assert result.warning_message is None
    assert output.read_bytes() == b"merged-video"


def test_merge_audio_falls_back_to_silent_video_with_warning(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    temp_video = tmp_path / "temp.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source-video")
    temp_video.write_bytes(b"silent-video")

    monkeypatch.setattr(Settings, "resolve_ffmpeg_path", lambda self: "/tmp/fake-ffmpeg")

    def fake_run(command, check, capture_output, text):
        return subprocess.CompletedProcess(command, 1, "", "audio merge failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WatermarkService()._merge_audio(source, temp_video, output)

    assert result.audio_merged is False
    assert result.warning_message is not None
    assert "audio merge failed" in result.warning_message
    assert output.read_bytes() == b"silent-video"


def test_merge_audio_without_audio_track_does_not_warn(monkeypatch, tmp_path):
    source = tmp_path / "source-no-audio.mp4"
    temp_video = tmp_path / "temp.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source-video")
    temp_video.write_bytes(b"silent-video")

    monkeypatch.setattr(Settings, "resolve_ffmpeg_path", lambda self: "/tmp/fake-ffmpeg")

    def fake_run(command, check, capture_output, text):
        output.write_bytes(b"video-without-audio")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WatermarkService()._merge_audio(source, temp_video, output)

    assert result.audio_merged is True
    assert result.warning_message is None
    assert output.read_bytes() == b"video-without-audio"
