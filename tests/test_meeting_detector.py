from mt_linux.detection.patterns import is_meeting_title


def test_is_meeting_title_matches_google_meet_titles():
    assert is_meeting_title("Meet - Weekly Standup")
    assert is_meeting_title("Google Meet")
    assert not is_meeting_title("Inbox")
