#!/usr/bin/env python3
"""Compare participant-labeled isolated finger steps with full-sequence phases."""
import argparse
import json
from pathlib import Path

import numpy as np

from review_micah_dynamic import load_envelopes, save
from spelltrain.dataset_policy import require_usable_capture


def compare(source, output):
    source=Path(source);output=Path(output)
    require_usable_capture(source)
    meta=json.loads((source/'metadata.json').read_text())
    if not meta.get('recording_complete') or meta.get('collection_variant')!='animation_steps':
        raise ValueError('Use a completed Animation Gesture step-mapping recording.')
    labels=json.loads((source/'animation-phase-intervals.json').read_text())['intervals']
    if meta.get('phase_reporting_enabled') is False:
        phases={'animation_cross_fingers':'cross_fingers','animation_curl_ring_pinky':'curl_ring_pinky',
                'animation_thumb_approach':'thumb_approach','animation_sequence':'full_sequence_unsegmented'}
        labels=[{**v,'phase':phases[v['selected_motion']['motion']]} for v in
            json.loads((source/'truth-values.json').read_text())['intervals'] if v['intended']]
    markers=json.loads((source/'animation-phase-markers.json').read_text())['markers']
    t,r,segments,timing=load_envelopes(source)
    rows=[]
    for index,label in enumerate(labels):
        ix=np.flatnonzero((t>=label['start'])&(t<label['end']))
        row={'phase_interval_index':index,**label,'usable_for_comparison':False,
             'context':'combined' if label['selected_motion']['motion']=='animation_sequence' else 'isolated'}
        if len(ix)<3 or len(np.unique(segments[ix]))!=1:
            row['review_reason']='Too short for three envelope samples, or crosses a recording gap; raw interval retained.'
        else:
            amplitude=np.sqrt(np.mean(r[ix]**2,axis=1))
            profile=np.median(r[ix]/np.maximum(np.linalg.norm(r[ix],axis=1,keepdims=True),1e-9),axis=0)
            profile/=max(np.linalg.norm(profile),1e-9)
            row.update(usable_for_comparison=True,median_rms_adc=float(np.median(amplitude)),
                       normalized_channel_profile=profile.tolist(),
                       envelope_samples=len(ix),duration_seconds=label['end']-label['start'])
        rows.append(row)
    comparisons=[]
    for phase in ['cross_fingers','curl_ring_pinky','thumb_approach']:
        isolated=[v for v in rows if v['phase']==phase and v['context']=='isolated' and v['usable_for_comparison']]
        combined=[v for v in rows if v['phase']==phase and v['context']=='combined' and v['usable_for_comparison']]
        result={'phase':phase,'isolated_intervals':len(isolated),'combined_intervals':len(combined)}
        if isolated and combined:
            a=np.median([v['normalized_channel_profile'] for v in isolated],axis=0)
            b=np.median([v['normalized_channel_profile'] for v in combined],axis=0)
            result.update(channel_pattern_cosine=float(a@b/(np.linalg.norm(a)*np.linalg.norm(b))),
                isolated_median_rms_adc=float(np.median([v['median_rms_adc'] for v in isolated])),
                combined_median_rms_adc=float(np.median([v['median_rms_adc'] for v in combined])))
        else:result['unavailable']='Need both isolated and combined examples of this reported phase.'
        comparisons.append(result)
    output.mkdir(parents=True,exist_ok=True)
    save(output/'step-comparison.json',{'source_session':meta['id'],'labels_modified':False,
        'role':'exploratory_component_to_sequence_comparison','test_condition':meta['test_condition'],
        'phase_summaries':rows,'comparisons':comparisons,'timing':timing,
        'missing_step_reports':[v for v in markers if v.get('skipped_preceding_phases')],
        'limitations':['Component starts and transitions are participant reports, not sensor-verified onsets.',
            'An isolated movement without a separately reported hold may mix movement and steady-pose EMG.',
            'Prepared starting poses differ by step; red preparation is not certified relaxed/clean negative truth.',
            'Action-and-Space-only recordings have no internal combined-sequence phase labels; those comparisons remain unavailable.',
            'Channel similarity is not detection accuracy or evidence of intention; no model is deployed.',
            'Three envelope samples is an analysis availability rule, not a valid event-duration threshold.']})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(12,9),layout='constrained')
    colors={'isolated':'#176b8e','combined':'#bd6631'}
    for ax,phase in zip(axes,['cross_fingers','curl_ring_pinky','thumb_approach']):
        for row in rows:
            if row['phase']!=phase or not row['usable_for_comparison']:continue
            ix=(t>=row['start'])&(t<row['end'])
            energy=np.sqrt(np.mean(r[ix]**2,axis=1))
            ax.plot(t[ix]-row['start'],energy,color=colors[row['context']],alpha=.55,lw=.9)
        ax.set(title=phase.replace('_',' '),xlabel='Seconds since reported phase start',ylabel='RMS (ADC counts)')
    fig.suptitle('Blue: isolated action · orange: combined-sequence phase · weak participant alignment')
    fig.savefig(output/'step-comparison.png',dpi=150);plt.close(fig)
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();compare(args.source,args.output)
