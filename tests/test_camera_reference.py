import json
import urllib.request
import urllib.error
import pytest
import numpy as np
from spelltrain.camera_reference import CameraReference,camera_posture,review_capture
from spelltrain.live_capture import LiveCapture
from test_live_test import setup,pump


def test_camera_chunk_retries_missing_chunks_and_durable_metadata(tmp_path):
    clock=[100.];capture=LiveCapture(tmp_path,lambda:clock[0],{})
    ref=CameraReference(capture,'video/webm',{'host_offset_seconds':100})
    ref.chunk(0,b'first');ref.chunk(0,b'first')
    with pytest.raises(ValueError,match='Conflicting'):ref.chunk(0,b'wrong')
    with pytest.raises(ValueError,match='missing'):ref.finish(2,2.)
    ref.chunk(1,b'second');result=ref.finish(2,2.)
    assert (capture.directory/result['file']).read_bytes()==b'firstsecond'
    assert result['complete'] and result['independently_reviewed'] is False
    capture.finish();report=review_capture(capture.directory)
    assert report['accuracy'] is None and report['reference']['complete']


def hand_fixture(opened=True):
    p=np.zeros((21,3));p[0]=[0,-1,0]
    for base,joint,distal,tip,x in ((5,6,7,8,-.3),(9,10,11,12,0),(13,14,15,16,.3),(17,18,19,20,.6)):
        p[base]=[x,0,0];p[joint]=[x,1,0];p[distal]=[x,1.5,.1] if opened else [x,.6,.2];p[tip]=[x,2,0] if opened else [x,.2,.3]
    image=p*.15+[.4,.4,0]
    return {'hands':[{'handedness':'Right','score':.99,'world':p.tolist(),'landmarks':image.tolist()}]}


def test_camera_posture_independent_rotation_invariant_and_unknown_when_unclear():
    assert camera_posture(hand_fixture())['label']=='open'
    fist=hand_fixture(False);assert camera_posture(fist)['label']=='fist'
    # No EMG or displayed spell enters the geometry calculation.
    fist['band_gesture']='Shield';assert camera_posture(fist)['label']=='fist'
    hand=fist['hands'][0];points=np.array(hand['world']);hand['world']=(points@np.array([[0,1,0],[-1,0,0],[0,0,1]])).tolist()
    assert camera_posture(fist)['label']=='fist'
    hand['handedness']='Left';assert camera_posture(fist)['label']=='unknown'
    assert camera_posture({'hands':[]})['label']=='unknown'


def test_camera_http_separates_observations_from_band_and_requires_matching_capture(tmp_path):
    tester,predictor,clock=setup(tmp_path);pump(tester,predictor,clock,'fist')
    port=tester.start(0,start_feed=False);base=f'http://127.0.0.1:{port}'
    def post(path,value):
        req=urllib.request.Request(base+path,data=json.dumps(value).encode(),headers={'X-Session-Token':tester.csrf})
        return json.load(urllib.request.urlopen(req))
    try:
        recording=tester.start_capture();capture_id=recording['id'];alignment={'host_offset_seconds':clock[0]-1.,'uncertainty_seconds':.01}
        value={'capture_id':capture_id,'alignment':alignment,'observation':{'client_t':1.,**hand_fixture()}}
        observed=post('/api/camera/observations',value)
        assert observed['posture']['label']=='open' and observed['agreement'] is False
        assert tester.status()['gesture']=='Sword equipped'
        with pytest.raises(urllib.error.HTTPError):post('/api/camera/observations',{**value,'capture_id':'wrong'})
        post('/api/camera/start',{'capture_id':capture_id,'mime':'video/webm','alignment':alignment})
        with pytest.raises(ValueError,match='camera upload'):tester.stop_capture()
        req=urllib.request.Request(base+'/api/camera/chunk?capture_id='+capture_id+'&index=0',data=b'media',headers={'X-Session-Token':tester.csrf})
        assert json.load(urllib.request.urlopen(req))['saved']
        post('/api/camera/finish',{'capture_id':capture_id,'count':1,'ended_client_t':2.})
        result=tester.stop_capture();assert result['complete']
        meta=json.loads((tester.capture_root/capture_id/'metadata.json').read_text())
        assert meta['camera_reference']['complete']
        report=json.loads((tester.capture_root/capture_id/'external-review.json').read_text())
        assert report['disagreements_at_receipt']==1 and report['accuracy'] is None
    finally:tester.close()
