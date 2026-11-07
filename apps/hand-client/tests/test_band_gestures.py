from handclient.band_gestures import CleanGesture, GestureCleaner
from handclient.kinesis_feed import BandGestureEvent


def message(sequence, finger="index", action="tap", derived="unknown", at_s=0.0, synthetic=False):
    return BandGestureEvent(sequence, sequence * 1000, at_s, finger, action, derived, synthetic)


def test_raw_and_derived_descriptions_of_one_tap_pass_once():
    cleaner = GestureCleaner()
    assert cleaner.clean(message(1, action="tap", at_s=1.0)) == CleanGesture(1.0, "index", "tap")
    assert cleaner.clean(message(2, action="unknown", derived="singleTap", at_s=1.05)) is None


def test_repeated_message_passes_once():
    cleaner = GestureCleaner()
    assert cleaner.clean(message(1, derived="singleTap")) is not None
    assert cleaner.clean(message(1, derived="singleTap")) is None


def test_separate_taps_both_pass():
    cleaner = GestureCleaner()
    assert cleaner.clean(message(1, action="tap", at_s=1.0)) is not None
    assert cleaner.clean(message(2, action="unknown", derived="singleTap", at_s=1.5)) is not None
    assert cleaner.clean(message(3, action="tap", at_s=1.8)) is not None


def test_drops_synthetic_and_unrecognised_messages():
    cleaner = GestureCleaner()
    assert cleaner.clean(message(1, synthetic=True)) is None
    assert cleaner.clean(message(2, action="partialPress")) is None
    assert cleaner.clean(message(3, finger="notApplicable")) is None


def test_normalises_swipes_and_identifies_pinches():
    cleaner = GestureCleaner()
    swipe = cleaner.clean(message(1, finger="thumb", action="left"))
    assert swipe == CleanGesture(0.0, "thumb", "swipe_left")
    assert not swipe.is_pinch
    assert cleaner.clean(message(2, finger="middle", action="press")).is_pinch
