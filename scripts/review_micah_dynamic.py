#!/usr/bin/env python3
"""Exploratory, label-preserving review of dynamic EMG; never fits live models."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from scipy import signal,stats,ndimage


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def clock_fit(native,receipt):
    """Robust affine fit to ten-second receipt-offset lower envelopes."""
    origin=float(native[0]);x=native-origin;y=receipt-native
    buckets=np.floor(x/10).astype(int);bx=[];by=[]
    for bucket in np.unique(buckets):
        where=np.flatnonzero(buckets==bucket);pick=where[np.argmin(y[where])]
        bx.append(x[pick]);by.append(y[pick])
    if len(bx)>=3:
        slope,intercept,lo,hi=stats.theilslopes(by,bx)
    else:slope=lo=hi=0.;intercept=float(np.min(y))
    mapped=native+intercept+slope*x
    return mapped,{'native_origin_seconds':origin,'offset_intercept_seconds':float(intercept),
        'offset_drift_ppm':float(slope*1e6),'drift_slope_interval_ppm':[float(lo*1e6),float(hi*1e6)],
        'method':'Theil-Sen affine fit to 10-second minimum receipt-minus-native offsets',
        'absolute_radio_latency_known':False,'physiological_event_times_verified':False}


def descriptor(rms,index,radius=10):
    if index-radius<0 or index+radius>=len(rms):return None
    window=rms[index-radius:index+radius+1].astype(float)
    floor=np.median(np.vstack([window[:3],window[-3:]]),axis=0)
    burst=np.maximum(window-floor,0)
    norm=np.linalg.norm(burst)
    return (burst.ravel()/norm).astype(np.float32) if norm>1e-6 else None


def consensus_templates(vectors):
    vectors=np.asarray(vectors,np.float32)
    similarity=vectors@vectors.T;np.fill_diagonal(similarity,-1)
    k=min(10,len(vectors)-1)
    if k<1:raise ValueError('Need multiple labeled snap examples for a consensus reference')
    agreement=np.median(np.sort(similarity,axis=1)[:,-k:],axis=1)
    # Robust core for review only: low-agreement examples are retained as outliers.
    threshold=float(np.quantile(agreement,.2))
    core=np.flatnonzero(agreement>=threshold)
    core_matrix=similarity[np.ix_(core,core)]
    loo=np.max(core_matrix,axis=1)
    return core,agreement,max(.65,float(np.quantile(loo,.1)))


def supplemental_review(source,output,t,r):
    """Quarantine ambiguous references and summarize all participant conditions."""
    labels=json.loads((source/'truth-values.json').read_text())['intervals']
    references=json.loads((output/'reference-quality.json').read_text());by_label={v['label_index']:v for v in references}
    queue=[];patterns={}
    for number,label in enumerate(labels):
        if not label['intended']:continue
        selected=label.get('selected_motion') or {};key=selected.get('motion','unknown')+':'+str(selected.get('effort'))
        where=(t>=label['start'])&(t<=label['end']);energy=np.sqrt(np.mean(r[where]**2,axis=1))
        entry=patterns.setdefault(key,{'intervals':0,'interval_median_rms_adc':[],'duration_seconds':[]})
        entry['intervals']+=1;entry['duration_seconds'].append(label['end']-label['start'])
        if len(energy):entry['interval_median_rms_adc'].append(float(np.median(energy)))
        if selected.get('motion')=='snap':
            reference=by_label.get(number)
            if reference is None or not reference['reference_core']:
                queue.append({'original_label_index':number,'start':label['start'],'end':label['end'],
                    'reason':'no_usable_peak' if reference is None else 'lower_consensus_waveform',
                    'original_label_retained':True,'automatic_relabel':False,
                    'note':'Could be a weak/rotated snap, missing signal, failed attempt, multiple actions or label mistake. Review before training; no one explanation is established.'})
    for entry in patterns.values():
        values=entry.pop('interval_median_rms_adc');durations=entry.pop('duration_seconds')
        entry['median_interval_seconds']=float(np.median(durations))
        entry['interval_median_rms_adc_quantiles']=list(map(float,np.quantile(values,[.25,.5,.75]))) if values else None
    save(output/'label-review-queue.json',{'items':queue,'original_labels_modified':False,'training_exclusions_automatically_applied':False})
    save(output/'condition-patterns.json',{'conditions':patterns,'note':'Dynamic EMG amplitude summaries, not physical force measurements or static-pose accuracy. Participant condition labels are retained.'})
    return {'snap_reference_review_queue':len(queue),'snap_reference_review_reasons':dict(Counter(v['reason'] for v in queue)),
            'condition_patterns':patterns}


def load_envelopes(source):
    meta=json.loads((source/'metadata.json').read_text());n=meta['counts']['emg']
    raw=np.empty((n,16,8),np.uint16);native=np.empty(n);receipt=np.empty(n)
    python=np.empty(n);seq=np.empty(n,np.int64);epoch=np.empty(n,np.int64)
    stored=np.empty(n);i=0
    secrets=re.compile(r'"(?:access_token|refresh_token|password|authorization|cookie|keychain|token)"\s*:|events\?token=',re.I)
    with (source/'streams.jsonl').open() as stream:
        for line in stream:
            if secrets.search(line):raise ValueError('Potential secret found; export stopped without printing it')
            row=json.loads(line)
            if row['kind']!='emg':continue
            p=row['packet'];raw[i]=p['samples'];native[i]=p['source_t']/1e6
            receipt[i]=p['source_uptime'];python[i]=row['host_uptime'];seq[i]=p['source_seq']
            timing=p.get('timing') or {};epoch[i]=timing.get('clock_epoch',0)
            stored[i]=timing.get('mapped_band_host_uptime_estimate',np.nan);i+=1
    if i!=n:raise ValueError('EMG count does not match complete capture metadata')
    mapped=np.empty(n);fits=[]
    for key in np.unique(epoch):
        where=np.flatnonzero(epoch==key);mapped[where],fit=clock_fit(native[where],receipt[where]);fits.append({'clock_epoch':int(key),**fit})
    boundaries=np.flatnonzero((np.diff(seq)!=1)|(np.diff(epoch)!=0)|(np.abs(np.diff(native)-16/2048)>2.5/2048))+1
    edges=np.r_[0,boundaries,n];rms=[];times=[];segments=[]
    sos=np.vstack([signal.butter(4,[20,450],fs=2048,btype='bandpass',output='sos'),
        signal.tf2sos(*signal.iirnotch(60,30,fs=2048))])
    for segment,(a,b) in enumerate(zip(edges[:-1],edges[1:])):
        x=raw[a:b].reshape(-1,8).astype(float)-32768
        if len(x)<64:continue
        filtered=signal.sosfilt(sos,x,axis=0,zi=signal.sosfilt_zi(sos)[:,:,None]*x[0])[0]
        size=len(filtered)//32
        rms.append(np.sqrt(np.mean(filtered[:size*32].reshape(size,32,8)**2,axis=1)))
        sample_t=(mapped[a:b,None]+np.arange(16)[None,:]/2048).ravel()-meta['started_host_uptime']
        times.append(sample_t[:size*32].reshape(size,32).mean(1));segments.append(np.full(size,segment))
    r=np.concatenate(rms);t=np.concatenate(times);s=np.concatenate(segments)
    del raw
    summary={'packets':n,'samples_per_channel':n*16,'sample_rate_hz':2048,'sequence_discontinuities':len(boundaries),
        'estimated_missing_batches':int(np.maximum(0,np.diff(seq)-1).sum()),'clock_fits':fits,
        'kinesis_to_python_seconds_quantiles':dict(zip(('p50','p95','p99','max'),map(float,np.quantile(python-receipt,[.5,.95,.99,1])))),
        'offline_vs_saved_host_mapping_seconds_quantiles':list(map(float,np.nanquantile(mapped-stored,[.05,.5,.95]))),
        'orientation_or_gyro_recorded':any(key.startswith('band_') for key in meta['counts']),
        'sample_time_convention':'Kinesis viewer start-of-batch convention; alternative end-of-batch differs by 15/2048 seconds (~7.3ms)',
        'gap_policy':'Filters reset at sequence/native-clock discontinuities; no gap samples are synthesized'}
    return t,r,s,summary


def review(source,output):
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    meta=json.loads((source/'metadata.json').read_text());truth=json.loads((source/'truth-values.json').read_text())
    if not meta.get('recording_complete'):raise ValueError('Finish recording before reviewing/exporting')
    labels=truth['intervals'];ends=np.array([v['end'] for v in labels]);starts=np.array([v['start'] for v in labels])
    print('Reading raw EMG and rebuilding sensor-time envelopes…',flush=True)
    t,r,segments,timing=load_envelopes(source)
    energy=np.sqrt(np.mean(r*r,axis=1));smooth=ndimage.median_filter(energy,size=3)
    label_index=np.clip(np.searchsorted(ends,t,side='right'),0,len(labels)-1)
    intended=np.array([labels[i]['intended'] for i in label_index])
    valid=(t>=0)&(t<=meta['duration_seconds'])
    baseline=smooth[valid&~intended];mad=max(1e-6,float(stats.median_abs_deviation(baseline,scale='normal')))
    peaks=[];widths=[];prominences=[]
    for segment in np.unique(segments):
        where=np.flatnonzero(segments==segment)
        if len(where)<25:continue
        found,properties=signal.find_peaks(smooth[where],distance=12,prominence=max(.15*mad,1.))
        if len(found):
            peaks.extend(where[found]);widths.extend(signal.peak_widths(smooth[where],found,rel_height=.5)[0]/64)
            prominences.extend(properties['prominences'])
    peak=np.array(peaks,dtype=int);widths=np.array(widths);prominences=np.array(prominences)
    usable=(t[peak]>=0)&(t[peak]<=meta['duration_seconds'])&(widths>=.015)&(widths<=.5)
    peak,widths,prominences=peak[usable],widths[usable],prominences[usable]
    # Each labeled snap interval contributes at most one reference, never a full-clip event label.
    references=[];vectors=[];reference_peaks=set()
    for number,label in enumerate(labels):
        if not label['intended'] or (label.get('selected_motion') or {}).get('motion')!='snap':continue
        choices=np.flatnonzero((t[peak]>=label['start'])&(t[peak]<=label['end']))
        if not len(choices):continue
        choose=choices[np.argmax(prominences[choices])];index=peak[choose]
        if index<10 or index+10>=len(t) or segments[index-10]!=segments[index+10]:continue
        vector=descriptor(r,index)
        if vector is None:continue
        references.append({'label_index':number,'peak_capture_t':float(t[index]),'interval_start':label['start'],'interval_end':label['end']})
        vectors.append(vector);reference_peaks.add(int(index))
    if len(vectors)<10:raise ValueError('Too few usable snap-labeled peaks for a robust exploratory reference')
    core,agreement,similarity_cutoff=consensus_templates(vectors);bank=np.asarray(vectors)[core]
    candidates=[];all_scores=[]
    for index,width,prominence in zip(peak,widths,prominences):
        if index<10 or index+10>=len(t) or segments[index-10]!=segments[index+10]:continue
        vector=descriptor(r,index)
        if vector is None:continue
        scores=bank@vector;nearest=int(np.argmax(scores));similarity=float(scores[nearest])
        number=int(label_index[index]);label=labels[number];center=float(t[index])
        prior=(t>=center-8)&(t<center-.2)&valid&~intended
        background=float(np.median(smooth[prior])) if prior.sum()>=32 else float(np.median(baseline))
        ratio=float(smooth[index]/max(background,1.))
        all_scores.append((center,similarity,label['intended']))
        if label['intended'] or similarity<similarity_cutoff:continue
        distance=float(min(abs(starts-center).min(),abs(ends-center).min()))
        category='boundary_overlap' if distance<.25 else 'unlabeled_snap_like_burst'
        surrounding=(np.abs(t-center)>.25)&(np.abs(t-center)<=.8)&(segments==segments[index])
        isolation=float(smooth[index]/max(1.,float(smooth[surrounding].max()))) if surrounding.any() else 1.
        nearest_reference=references[int(core[nearest])]
        candidates.append({'capture_t_seconds':center,'time_mm_ss':f'{int(center//60):02}:{center%60:06.3f}',
            'original_label':'non_intended','proposed_label':None,'independently_reviewed':False,
            'category':category,'nearest_label_boundary_seconds':distance,'template_similarity':similarity,
            'local_energy_ratio':ratio,'peak_width_half_prominence_seconds':float(width),
            'prominence_adc':float(prominence),'nearest_labeled_reference_capture_t':nearest_reference['peak_capture_t'],
            'isolation_ratio':isolation,'review_context':'isolated_snap_like' if isolation>=2 else 'dynamic_cluster_ambiguous',
            'reference_label_index':nearest_reference['label_index'],
            'rank_score':float(similarity*min(ratio,8)*min(float(prominence)/mad,8)*np.clip(isolation,.25,4)),
            'review_window_start':max(0,center-1),'review_window_end':min(meta['duration_seconds'],center+1),
            'note':'Signal similarity cannot establish intention; dynamic jerks, contact or grip changes may resemble a snap.'})
    candidates.sort(key=lambda row:row['rank_score'],reverse=True)
    for i,row in enumerate(candidates):row['review_rank']=i+1
    for i,row in enumerate(references):row.update(consensus_agreement=float(agreement[i]),reference_core=bool(i in core))
    by_motion=Counter((v.get('selected_motion') or {}).get('motion') for v in labels if v['intended'])
    report={'session_id':source.name,'test_condition':'dynamic','analysis_role':'exploratory_label_quality_review',
        'labels_are_primary':True,'original_labels_modified':False,'automatically_retrained':False,
        'duration_seconds':meta['duration_seconds'],'intended_interval_count':sum(v['intended'] for v in labels),
        'intended_intervals_by_motion':dict(by_motion),'timing':timing,
        'snap_labeled_intervals':sum(v['intended'] and (v.get('selected_motion') or {}).get('motion')=='snap' for v in labels),
        'usable_snap_reference_peaks':len(references),'robust_reference_core_size':len(core),
        'reference_similarity_threshold':similarity_cutoff,'candidate_count':len(candidates),
        'candidate_categories':dict(Counter(row['category'] for row in candidates)),
        'top_review_candidates':candidates[:20],
        'ranking_context':'Prioritize isolated bursts over peaks embedded in larger dynamic-motion clusters; neither establishes intention.',
        'method':'Causal 20–450Hz bandpass + 60Hz notch, 15.625ms eight-channel RMS. Burst descriptors subtract edge baseline and normalize amplitude. A mutually similar 80% core of peaks inside participant snap windows supplies an exploratory template bank; non-intended bursts are ranked against it.',
        'limitations':['This is one dynamic wearing session, not an independent accuracy evaluation.',
            'Peak-in-clip references are weak examples; mistaken labels or multiple actions can contaminate them. Consensus reduces but cannot eliminate this.',
            'Temporal/channel resemblance is not proof of a snap or mental intent. No proposed correction is automatically training truth.',
            'Events within 250ms of a key boundary are separated as timing/overlap cases.',
            'EMG-only capture: gyro, orientation and camera cannot independently verify this recording.',
            'Band/host alignment uses a receipt-offset lower envelope. Absolute transport latency, physiological onset and within-batch timestamp convention remain uncalibrated.']}
    selections=json.loads((source/'motion-selections.json').read_text())
    for candidate in candidates:
        prior=[v for v in selections if v['capture_t']<=candidate['capture_t_seconds']]
        candidate['selected_motion_context']=prior[-1]['motion'] if prior else None
    save(output/'review-candidates.json',candidates);save(output/'reference-quality.json',references)
    report.update(supplemental_review(source,output,t,r))
    save(output/'review-report.json',report)
    with (output/'review-candidates.csv').open('w',newline='') as stream:
        if candidates:
            writer=csv.DictWriter(stream,fieldnames=list(candidates[0]),lineterminator="\n");writer.writeheader();writer.writerows(candidates)
    plot(output,t,smooth,intended,candidates,meta['duration_seconds'])
    np.savez_compressed(output/'envelope-review.npz',capture_t=t,rms_8_channels=r,segment=segments,original_intended=intended)
    print(json.dumps({k:report[k] for k in ('snap_labeled_intervals','usable_snap_reference_peaks','robust_reference_core_size','candidate_count','candidate_categories')}),flush=True)
    return report


def plot(output,t,energy,intended,candidates,duration):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10})
    fig,ax=plt.subplots(figsize=(15,4));ax.plot(t[::4],energy[::4],lw=.5,color='#315f8e')
    scale=np.quantile(energy,.99);ax.fill_between(t[::4],0,scale,where=intended[::4],color='#69ae80',alpha=.2,label='Participant intended')
    for candidate in candidates[:20]:ax.axvline(candidate['capture_t_seconds'],color='#ba4747',alpha=.5,lw=.8)
    ax.set(xlim=(0,duration),yscale='symlog',xlabel='Capture seconds (estimated sensor-time alignment)',ylabel='Filtered EMG RMS (ADC)',title='Dynamic recording — original intent windows and top review candidates')
    ax.legend();fig.tight_layout();fig.savefig(output/'dynamic-overview.png',dpi=150);plt.close(fig)
    selected=([row for row in candidates if row['category']=='unlabeled_snap_like_burst'][:6] or candidates[:6])
    if selected:
        fig,axes=plt.subplots(len(selected),1,figsize=(12,max(3,2*len(selected))),squeeze=False)
        for ax,row in zip(axes[:,0],selected):
            where=(t>=row['review_window_start'])&(t<=row['review_window_end']);x=t[where]
            ax.plot(x,energy[where],lw=1);top=max(1,float(energy[where].max()))
            ax.fill_between(x,0,top,where=intended[where],color='#69ae80',alpha=.25)
            ax.axvline(row['capture_t_seconds'],color='#ba4747',ls='--')
            ax.set_title(f"Review #{row['review_rank']} · {row['time_mm_ss']} · similarity {row['template_similarity']:.3f} · original label: non-intended")
            ax.set_ylabel('EMG RMS')
        axes[-1,0].set_xlabel('Capture seconds — proposals only; labels unchanged')
        fig.tight_layout();fig.savefig(output/'candidate-windows.png',dpi=150);plt.close(fig)


def publish_original(source,target):
    target.mkdir(parents=True,exist_ok=True);files={}
    for path in sorted(source.iterdir()):
        if not path.is_file():raise ValueError('Unexpected source subdirectory; review before publication')
        sha=digest(path)
        if path.name=='streams.jsonl':
            destination=target/'streams.jsonl.gz'
            with destination.open('wb') as out:
                with gzip.GzipFile(filename='',fileobj=out,mode='wb',compresslevel=6,mtime=0) as compressed:
                    with path.open('rb') as stream:shutil.copyfileobj(stream,compressed)
            verify=hashlib.sha256()
            with gzip.open(destination,'rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):verify.update(block)
            if verify.hexdigest()!=sha:raise ValueError('Lossless archive verification failed')
        else:
            # Labels and metadata are preserved byte for byte.
            destination=target/path.name;shutil.copyfile(path,destination)
        files[path.name]={'original_sha256':sha,'published_file':destination.name,
                         'published_sha256':digest(destination),'published_bytes':destination.stat().st_size}
        if destination.stat().st_size>=95*1024*1024:raise ValueError('Published file is too large for ordinary Git; split archive first')
    save(target/'source-manifest.json',{'session_id':source.name,'test_condition':'dynamic','original_files':files,
        'labels_modified':False,'raw_archive':'gzip decompression reproduces the original streams.jsonl SHA-256'})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Choose a new output directory; original publications are immutable')
    report=review(source,output/'analysis')
    print('Compressing and verifying original data for publication…',flush=True)
    publish_original(source,output/'original')
    save(output/'dataset.json',{'session_id':source.name,'contributor':'Micah','test_condition':'dynamic',
        'dataset_role':'training_development_only','original_labels':'original/truth-values.json',
        'review_report':'analysis/review-report.json','labels_are_primary':True,'review_candidates_are_ground_truth':False,
        'duration_seconds':report['duration_seconds'],'capture_motion_context_available':report['timing']['orientation_or_gyro_recorded']})


if __name__=='__main__':main()
