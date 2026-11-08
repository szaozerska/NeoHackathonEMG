import base64
import json
import numpy as np
import pytest
from spelltrain.session import Session
from spelltrain.supplemental import SupplementalTraining,protocol,PROTOCOL,LABEL_FILE


def setup(tmp_path):
    session=Session(tmp_path/'extra','player-a')
    session.meta['training_profile']='supplemental'
    session.meta['dataset_role']='development'
    clock=[0.];session.now=lambda:clock[0]
    return session,SupplementalTraining(session),clock


def capture(session,training,clock):
    start=clock[0]
    training.start(training.status()['current']['id'])
    for i in range(768):
        training.observe({'received':start+i/128,'samples':np.arange(128).reshape(16,8),
                          'source_seq':i,'source_uptime':session.meta['origin_monotonic']+start+i/128})
    clock[0]=start+6
    return training.finish()


def reference(row):
    return {'result_id':row['id'],'mime':'video/webm;codecs=vp8,opus',
        'data':base64.b64encode(b'reference'*100).decode(),
        'alignment':{'recorder_start_ms':0.,'start_request_ms':10.,'start_ack_ms':20.,
                     'stop_requested_ms':6100.,'server_trial_start':row['start']}}


def test_focused_protocol_has_single_snaps_and_does_not_label_cues_as_events():
    trials=protocol('extra')
    assert len(trials)==40 and len({t['id'] for t in trials})==40
    assert trials==protocol('extra')
    for repetition in (1,2):
        block=[t for t in trials if t['repetition']==repetition]
        assert len(block)==20 and block[0]['condition']=='rest-supported'
        snaps=[t for t in block if t['movement']=='snap']
        assert len(snaps)==5 and all(t['expected_snap_count']==1 for t in snaps)
        assert all(t['hand_state']=='fist' for t in block if t['condition'].startswith('fist-'))
        assert all(t['hand_state']=='unlabeled' for t in block if t['movement']=='transition')


def test_reference_required_confirmation_retry_and_durable_storage(tmp_path):
    session,training,clock=setup(tmp_path)
    try:
        row=capture(session,training,clock)
        assert row['received'] and row['protocol']==PROTOCOL
        with pytest.raises(ValueError,match='reference'):training.confirm(row['id'],True)
        training.attach_reference(**reference(row))
        training.confirm(row['id'],True)
        assert training.status()['completed']==1
        reloaded=SupplementalTraining(session)
        assert reloaded.status()['completed']==1
        saved=json.loads((session.directory/LABEL_FILE).read_text())[-1]
        ref=saved['reference'];assert (session.directory/ref['file']).read_bytes()==b'reference'*100
        assert not ref['event_times_verified'] and not ref['hardware_latency_calibrated']
        assert session.annotations==[]
        # Lost reference can be rejected and retried without throwing away earlier progress.
        next_=capture(session,training,clock);training.confirm(next_['id'],False)
        assert training.status()['completed']==1
    finally:session.close()


def test_references_validate_capture_binding_format_timing_and_no_overwrite(tmp_path):
    session,training,clock=setup(tmp_path)
    try:
        row=capture(session,training,clock);value=reference(row)
        with pytest.raises(ValueError):training.attach_reference(**{**value,'mime':'text/html'})
        with pytest.raises(ValueError):training.attach_reference(**{**value,'data':'not base64'})
        with pytest.raises(ValueError):training.attach_reference(**{**value,'alignment':{**value['alignment'],'server_trial_start':99.}})
        with pytest.raises(ValueError):training.attach_reference(**{**value,'alignment':{**value['alignment'],'stop_requested_ms':0.}})
        training.attach_reference(**value)
        assert training.attach_reference(**value)['reference']
        with pytest.raises(ValueError):training.attach_reference(**{**value,'data':base64.b64encode(b'other'*100).decode()})
    finally:session.close()


def test_live_reference_api_and_video_range_playback(tmp_path):
    import urllib.request,urllib.error
    from spelltrain.recorder import Recorder
    session,_,clock=setup(tmp_path);recorder=Recorder(session);port=recorder.start_web(0)
    base=f'http://127.0.0.1:{port}'
    try:
        html=urllib.request.urlopen(base).read().decode()
        assert 'Extra gesture training' in html
        token=html.split("const token='")[1].split("'")[0]
        row=capture(session,recorder.shield_training,clock)
        value=reference(row);value['id']=value.pop('result_id')
        req=urllib.request.Request(base+'/api/reference',data=json.dumps(value).encode(),headers={'X-Session-Token':token})
        result=json.load(urllib.request.urlopen(req))
        assert result['reference'] and result['id']==row['id']
        response=urllib.request.urlopen(urllib.request.Request(base+'/api/reference?id='+row['id'],headers={'Range':'bytes=0-8'}))
        assert response.status==206 and response.read()==b'reference'
        with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(base+'/api/reference?id=unknown')
    finally:recorder.close()


def test_binary_reference_upload_preserves_codec_commas_and_exact_payload(tmp_path):
    import urllib.request
    from urllib.parse import quote
    from spelltrain.recorder import Recorder
    session,_,clock=setup(tmp_path);recorder=Recorder(session);port=recorder.start_web(0)
    base=f'http://127.0.0.1:{port}'
    try:
        html=urllib.request.urlopen(base).read().decode()
        assert "fetch('/api/reference-binary'" in html and 'FileReader' not in html
        token=html.split("const token='")[1].split("'")[0]
        row=capture(session,recorder.shield_training,clock)
        meta=reference(row)
        payload=bytes(range(256))*400  # Larger than the usual JSON limit, includes non-text bytes.
        req=urllib.request.Request(base+'/api/reference-binary',data=payload,headers={
            'X-Session-Token':token,'X-Result-Id':row['id'],'Content-Type':'video/webm;codecs=vp8,opus',
            'X-Reference-Alignment':quote(json.dumps(meta['alignment']))})
        result=json.load(urllib.request.urlopen(req))
        assert result['reference']['bytes']==len(payload)
        assert (session.directory/result['reference']['file']).read_bytes()==payload
        recorder.shield_training.confirm(row['id'],True)
        assert recorder.shield_training.status()['completed']==1
    finally:recorder.close()


def test_resume_supplemental_preserves_trial_progress_pending_and_stream(tmp_path):
    from spelltrain.cli import resume_supplemental
    from spelltrain.common import write_json
    session,training,clock=setup(tmp_path)
    session.meta.update(mode='emg_only',band_file=str((tmp_path/'raw.jsonl').resolve()))
    row=capture(session,training,clock)
    training.attach_reference(**reference(row));training.confirm(row['id'],True)
    pending=capture(session,training,clock)
    session.append({'kind':'emg','t':0.,'samples':[[0]*8]})
    directory=session.directory;origin=session.meta['origin_monotonic'];session.close()
    before=(directory/'streams.jsonl').read_bytes()
    resumed=resume_supplemental(directory,'player-a',str(tmp_path/'raw.jsonl'),True)
    try:
        state=SupplementalTraining(resumed).status()
        assert state['completed']==1 and state['pending']['id']==pending['id']
        assert resumed.meta['origin_monotonic']==origin
        assert resumed.counts['emg']==1 and not resumed.meta['recording_closed']
        assert (directory/'streams.jsonl').read_bytes()==before
        resumed.append({'kind':'prediction','t':1.})
    finally:resumed.close()
