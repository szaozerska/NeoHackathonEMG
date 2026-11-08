import json

import pytest
from spelltrain.dataset_policy import require_usable_capture
from spelltrain.feedback_update import capture_features


@pytest.mark.parametrize('session',['20261108-021109-c4c1082d','20261108-024600-0df8f41b'])
def test_rejected_session_is_blocked_by_id_before_loading_signals(tmp_path,session):
    path = tmp_path/session
    path.mkdir()
    with pytest.raises(ValueError, match='DO NOT USE'):
        capture_features(path)


@pytest.mark.parametrize('marker', ['DO_NOT_USE.json', 'DO_NOT_USE.md'])
def test_rejection_survives_folder_rename_with_marker(tmp_path, marker):
    (tmp_path/marker).write_text('{}')
    with pytest.raises(ValueError, match='DO NOT USE'):
        require_usable_capture(tmp_path)


def test_renamed_copy_is_blocked_by_original_metadata_id(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({'id':'20261108-021109-c4c1082d'}))
    with pytest.raises(ValueError, match='DO NOT USE'):
        require_usable_capture(tmp_path)


def test_other_captures_remain_eligible_unless_explicitly_rejected(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({'id':'different-session'}))
    require_usable_capture(tmp_path)
    (tmp_path/'metadata.json').write_text(json.dumps({'do_not_use':True}))
    with pytest.raises(ValueError, match='DO NOT USE'):
        require_usable_capture(tmp_path)
