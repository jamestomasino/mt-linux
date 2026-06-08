from mt_linux.diarization.diarizer import DiarizationSegment


class _FakeTurn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class _FakeAnnotation:
    def itertracks(self, yield_label: bool = False):
        yield _FakeTurn(0.0, 1.5), "_", "SPEAKER_00"


class _FakeDiarizeOutput:
    def __init__(self):
        self.exclusive_speaker_diarization = _FakeAnnotation()


def test_diarize_supports_current_pyannote_output_shape():
    diarizer = object.__new__(__import__("mt_linux.diarization.diarizer", fromlist=["PyannoteDiarizer"]).PyannoteDiarizer)
    diarizer.pipeline = lambda path, **kwargs: _FakeDiarizeOutput()
    diarizer.num_speakers = None
    segments = diarizer.diarize(__import__("pathlib").Path("/tmp/test.wav"))
    assert segments == [DiarizationSegment(start=0.0, end=1.5, speaker="SPEAKER_00")]
