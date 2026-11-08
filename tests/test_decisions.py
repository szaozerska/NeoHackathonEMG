import pytest
from spelltrain.decisions import DecisionMemory,EffortMemory


def advance(memory,probabilities,start,seconds):
    for i in range(round(seconds/.05)):
        memory.feed(probabilities,start+i*.05)
    return start+seconds


def test_fist_memory_survives_brief_none_pulses_but_explicit_open_releases():
    m=DecisionMemory();t=advance(m,{'fist':.95,'none':.04,'open':.01},0,.5)
    assert m.label=='fist'
    for _ in range(4):
        t=advance(m,{'fist':.1,'none':.88,'open':.02},t,.15)
        assert m.label=='fist'
        t=advance(m,{'fist':.94,'none':.05,'open':.01},t,.35)
        assert m.label=='fist'
    advance(m,{'fist':.01,'none':.01,'open':.98},t,.45)
    assert m.label=='open'
    assert m.history[-1][0]-m.history[0][0]<=.8+1e-9


def test_memory_returns_to_relaxation_and_never_latches_on_ambiguity_forever():
    m=DecisionMemory();t=advance(m,{'fist':.95,'none':.04,'open':.01},0,.5)
    t=advance(m,{'fist':.05,'none':.94,'open':.01},t,.6)
    assert m.label=='none'
    t=advance(m,{'fist':.95,'none':.04,'open':.01},t,.5)
    assert m.label=='fist'
    advance(m,{'fist':.42,'none':.46,'open':.12},t,1.2)
    assert m.label=='none'


def test_sensor_clock_not_receipt_spacing_drives_memory_and_real_gaps_reset():
    a=DecisionMemory();b=DecisionMemory()
    evidence=[{'fist':.95,'none':.04,'open':.01}]*20
    sequential=[a.feed(p,i*.05) for i,p in enumerate(evidence)]
    burst=[]
    for batch in range(2):
        burst += [b.feed(evidence[i],i*.05) for i in range(batch*10,batch*10+10)]
    assert sequential==burst and b.label=='fist'
    assert b.feed({'fist':.95,'none':.04,'open':.01},3.)=='none'
    with pytest.raises(ValueError):b.feed({'fist':float('nan')},3.05)


def test_effort_memory_rejects_small_boundary_jitter_but_follows_sustained_changes():
    m=EffortMemory()
    for i in range(20):
        p={'light':.01,'medium':.51 if i%2 else .49,'firm':.48 if i%2 else .50}
        result=m.feed(p,i*.05)
        if i==0:initial=result['label']
        assert result['label']==initial
    for i in range(20,40):result=m.feed({'light':.01,'medium':.04,'firm':.95},i*.05)
    assert result['label']=='firm'
    for i in range(40,60):result=m.feed({'light':.95,'medium':.04,'firm':.01},i*.05)
    assert result['label']=='light'
