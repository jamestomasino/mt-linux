from mt_linux.models import TranscriptSegment
from mt_linux.transcription.cleanup import suppress_low_signal_segments


def test_suppress_low_signal_segments_drops_punctuation_only_mic_segments():
    kept = suppress_low_signal_segments(
        [
            TranscriptSegment(start=0.0, end=0.5, text=". . .", confidence=-1.2, no_speech_prob=0.95, track="mic"),
            TranscriptSegment(start=0.5, end=1.0, text="Real sentence here", confidence=-0.2, no_speech_prob=0.1, track="mic"),
        ],
        track="mic",
    )
    assert [segment.text for segment in kept] == ["Real sentence here"]


def test_suppress_low_signal_segments_drops_common_silence_hallucinations_on_mic():
    kept = suppress_low_signal_segments(
        [
            TranscriptSegment(start=0.0, end=0.8, text="Thank you", confidence=-1.1, no_speech_prob=0.82, track="mic"),
            TranscriptSegment(start=0.8, end=1.3, text="Amen", confidence=-1.0, no_speech_prob=0.7, track="mic"),
            TranscriptSegment(start=1.3, end=2.0, text="We should ship that change", confidence=-0.3, no_speech_prob=0.05, track="mic"),
        ],
        track="mic",
    )
    assert [segment.text for segment in kept] == ["We should ship that change"]


def test_suppress_low_signal_segments_leaves_app_track_unchanged():
    segments = [
        TranscriptSegment(start=0.0, end=0.8, text="Thank you", confidence=-1.1, no_speech_prob=0.82, track="app"),
    ]
    kept = suppress_low_signal_segments(segments, track="app")
    assert [segment.text for segment in kept] == ["Thank you"]
