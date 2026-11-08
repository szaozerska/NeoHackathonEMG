import numpy as np
from spelltrain.signals import SignalWindows
from spelltrain.feeds import sse_events, normalize_sse, decode_kinesis_raw, BatchTimeline, KINESIS_STREAM_ADAPTER


def test_filter_features_are_invariant_to_batch_boundaries():
    rng=np.random.default_rng(9)
    x=rng.integers(32000,33500,(3000,8),dtype=np.uint16)
    t=np.arange(len(x))/2048
    one=SignalWindows().feed(x,t)
    stream=SignalWindows()
    many=[]
    for a in range(0,len(x),16):
        many+=stream.feed(x[a:a+16],t[a:a+16])
    assert [(a['kind'],a['t']) for a in one]==[(a['kind'],a['t']) for a in many]
    np.testing.assert_allclose(np.array([r['x'].sum() for r in one]),np.array([r['x'].sum() for r in many]),rtol=1e-10)


def test_gap_resets_filter_and_requires_warmup():
    signal=SignalWindows()
    x=np.ones((1000,8))*32768
    signal.feed(x,np.arange(1000)/2048)
    assert signal.feed(x[:16],2+np.arange(16)/2048)==[]


def test_sse_multiline_and_layout():
    messages=list(sse_events([b': heartbeat\n',b'event: emg\n',b'data: {"samples":\n',b'data: [[1,2,3,4,5,6,7,8]]}\n',b'\n']))
    assert normalize_sse(messages[0][1],messages[0][0])['samples'][0][-1]==8


def test_actual_upstream_hex_protobuf_layout():
    def varint(v):
        b=[]
        while v>=128:b.append((v&127)|128);v>>=7
        return bytes(b+[v])
    samples=np.arange(128,dtype='<u2')
    payload=b'\x08'+varint(7)+b'\x10'+varint(100000)+b'\x1a'+varint(256)+samples.tobytes()
    row=decode_kinesis_raw({'kind':'0x0200020a','payload':payload.hex(),'uptime':100.})
    assert row['source_seq']==7
    assert row['samples'][1]==list(range(8,16))


def test_sequence_gap_not_hidden_by_arrival_rate():
    clock=BatchTimeline()
    clock.align({'samples':[[0]*8]*16,'source_seq':1},1.)
    row=clock.align({'samples':[[0]*8]*16,'source_seq':3},1.008)
    assert row['gap']


def test_feed_without_sequence_can_produce_contiguous_windows():
    clock=BatchTimeline()
    first=clock.align({'samples':[[0]*8]*16},1.)
    second=clock.align({'samples':[[0]*8]*16},1.+16/2048)
    assert not first['gap'] and not second['gap']
    assert second['timing']=='sequence_receive_anchored'


def test_tail_waits_for_new_recording_file(tmp_path):
    import json
    import threading
    import time
    from spelltrain.feeds import tail_kinesis
    stop=threading.Event()
    received=threading.Event()
    errors=[]
    filename=tmp_path/'future.jsonl'
    def callback(packet):
        assert packet['source_seq']==7
        received.set()
    thread=threading.Thread(target=tail_kinesis,args=(filename,stop,callback,errors.append))
    thread.start()
    try:
        time.sleep(.15)
        assert thread.is_alive() and not errors
        # Protobuf fields: sequence 7, timestamp 100, 256 sample bytes.
        payload=b'\x08\x07\x10\x64\x1a\x80\x02'+np.arange(128,dtype='<u2').tobytes()
        filename.write_text(json.dumps({'kind':'0x0200020a','payload':payload.hex(),'uptime':100.})+'\n')
        assert received.wait(2)
        assert not errors
    finally:
        stop.set()
        thread.join(2)


def test_kinesis_stream_emg_event_keeps_host_uptime_and_band_clock():
    rows=[[i*8+c for c in range(8)] for i in range(16)]
    payload={'schema_version':1,'type':'emg','stream_session_id':'s','event_sequence':40,'host_time_s':812.25,
             'band_timestamp_us':123456,'payload':{'sequence':9,'sample_rate_hz':2048,'layout':'sample_major','values':rows}}
    packet=normalize_sse(payload,'emg',KINESIS_STREAM_ADAPTER)
    assert packet=={'samples':rows,'source_seq':9,'source_t':123456,'source_uptime':812.25,
                    'stream_session':'s'}
    assert normalize_sse({**payload,'type':'status'},'status',KINESIS_STREAM_ADAPTER) is None
    assert 'source_uptime' not in normalize_sse({'type':'emg','samples':rows},'emg')
