from mt_linux.models import TranscriptSegment
from mt_linux.protocol.quality import has_substantive_transcript


def test_has_substantive_transcript_accepts_real_discussion():
    segments = [
        TranscriptSegment(start=0.0, end=3.0, text="We should move the launch to next Thursday."),
        TranscriptSegment(start=3.0, end=7.0, text="That gives analytics enough time to validate the dashboard."),
        TranscriptSegment(start=7.0, end=10.0, text="Agreed, and Jim will update the team in Slack tomorrow."),
    ]
    assert has_substantive_transcript(segments) is True


def test_has_substantive_transcript_rejects_placeholder_or_empty_material():
    segments = [
        TranscriptSegment(start=0.0, end=1.0, text="you"),
        TranscriptSegment(start=1.0, end=2.0, text="yeah"),
        TranscriptSegment(start=2.0, end=3.0, text="okay"),
        TranscriptSegment(start=3.0, end=4.0, text=""),
    ]
    assert has_substantive_transcript(segments) is False
