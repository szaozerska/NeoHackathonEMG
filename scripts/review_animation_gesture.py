#!/usr/bin/env python3
"""Rank gesture-like red intervals and onset changes; never relabel finger steps or intent."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import signal

from analyze_micah_patterns import extract
from review_micah_dynamic import save


def review(source, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    data, summary, labels = extract(source, output/'static-features.npz')
    green = (data['intent']=='intended') & (data['margin']>=.25)
    red = data['intent']=='non_intended'
    groups = np.unique(data['group'][green])
    if len(groups)<2:
        raise ValueError('Need at least two participant green intervals for cross-interval reference checks')
    profiles = data['X'][:,1:9].astype(float)
    bank = np.array([np.median(profiles[green & (data['group']==g)],axis=0) for g in groups])
    bank /= np.linalg.norm(bank,axis=1,keepdims=True)
    similarity = profiles @ bank.T
    other = similarity[green].copy()
    for i,g in enumerate(groups):other[data['group'][green]==g,i]=-1
    cutoff = max(.97,float(np.quantile(other.max(1),.10)))
    energy = np.expm1(data['X'][:,0]);low,high=np.quantile(energy[green],[.025,.975])
    match = red & (similarity.max(1)>=cutoff) & (energy>=low*.75) & (energy<=high*1.5)
    spans=[];current=[]
    for i in np.flatnonzero(match):
        if current and (data['group'][i]!=data['group'][current[-1]] or data['start'][i]-data['start'][current[-1]]>.1):
            spans.append(current);current=[]
        current.append(int(i))
    if current:spans.append(current)
    candidates=[]
    boundaries=np.array([v['start'] for v in labels]+[labels[-1]['end']])
    for indices in spans:
        start=float(data['start'][indices[0]]);end=float(data['end'][indices[-1]])
        if end-start<.35:continue
        score=float(np.median(similarity[indices].max(1)))
        candidates.append({'start':start,'end':end,'duration_seconds':end-start,
            'time_mm_ss':f'{int(start//60):02}:{start%60:05.2f}',
            'median_channel_similarity':score,'median_rms_adc':float(np.median(energy[indices])),
            'nearest_label_boundary_seconds':float(np.min(np.abs(boundaries-(start+end)/2))),
            'original_label':'non_intended','proposed_label':None,'human_reviewed':False,
            'classification':'gesture_like_red_review_candidate',
            'note':'Similar channel pattern and amplitude do not establish intended action or a label mistake.'})
    candidates.sort(key=lambda v:v['duration_seconds']*v['median_channel_similarity'],reverse=True)
    onset=[]
    for g in groups:
        label=labels[g];ix=np.flatnonzero((data['group']==g)&(data['end']<=label['start']+4))
        if len(ix)<3:continue
        distance=np.linalg.norm(np.diff(profiles[ix],axis=0),axis=1)
        peaks,_=signal.find_peaks(distance,prominence=.02,distance=3)
        onset.append({'original_green_interval':int(g),'space_down_seconds':label['start'],
            'space_up_seconds':label['end'],
            'candidate_channel_change_times_seconds':[float(data['end'][ix[p+1]]) for p in peaks],
            'phase_assignment':None,'verified_internal_finger_timestamps':False})
    report={'source_session':summary['session_id'],'participant_labels_modified':False,
        'rejected_capture_used':False,'analysis_role':'exploratory_review_not_training',
        'datasets':summary,'green_intervals_used':len(groups),'profile_similarity_cutoff':cutoff,
        'green_rms_adc_p025_p975':[float(low),float(high)],'red_review_candidates':candidates,
        'green_onset_change_candidates':onset,
        'method':'Compare amplitude-normalized eight-channel RMS with per-green-interval median references. Threshold uses leave-other-interval-out green similarity with a 0.97 floor, plus a broad green-amplitude range. No red label is used as certain negative truth.',
        'limitations':['Only three green examples in this static recording; this is not an accuracy evaluation.',
            'Sustained green references may miss short transition or thumb-tap signatures.',
            'Change points may be noise, finger transitions, tension or contact changes; no finger-step identity is inferred.',
            'No gyro/orientation in this recording; arm rotation cannot be reconstructed from this EMG-only stream.']}
    save(output/'animation-review.json',report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(13,7),sharex=True,layout='constrained')
    axes[0].plot(data['end'],energy,color='black',lw=.6);axes[0].set(yscale='log',ylabel='RMS (ADC counts)')
    axes[1].plot(data['end'],similarity.max(1),color='#216d96',lw=.7)
    axes[1].axhline(cutoff,color='gray',ls='--');axes[1].set(ylabel='Channel-pattern similarity',xlabel='Recording seconds')
    for label in labels:
        if label['intended']:
            for ax in axes:ax.axvspan(label['start'],label['end'],alpha=.16,color='green')
    for row in candidates:
        for ax in axes:ax.axvspan(row['start'],row['end'],alpha=.25,color='orange')
    axes[0].set_title('Animation Gesture: original green labels; orange = red intervals for review only')
    fig.savefig(output/'animation-review.png',dpi=150);plt.close(fig)
    lines=['# Static Animation Gesture review','',
        'Original Spacebar labels are unchanged. Orange/review candidates are signal matches, not confirmed intention or corrected labels. The rejected zero-intended session was not used.','',
        '| Red interval start | End (seconds) | Duration | Median channel similarity |',
        '|---|---:|---:|---:|']
    for row in candidates[:20]:lines.append(f"| {row['time_mm_ss']} | {row['end']:.2f} | {row['duration_seconds']:.2f}s | {row['median_channel_similarity']:.3f} |")
    if not candidates:lines+=['','No sustained red spans passed this conservative reference-matching rule; that does not prove absence of contamination.']
    lines+=['','The complete list, reference threshold, timing checks and candidate onset changes are in `animation-review.json`. Internal crossing/tap timestamps remain unverified. Preserve every original interval and keep this review separate from training labels.']
    (output/'REVIEW.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'green_intervals':len(groups),'red_candidates':candidates[:12],'onset_candidates':onset},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();review(args.source,args.output)
