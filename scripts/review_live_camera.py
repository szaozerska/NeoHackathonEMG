"""Export local camera evidence for review; never infer ground-truth snap times."""
import argparse,hashlib,json,subprocess
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks
from spelltrain.camera_reference import review_capture
parser=argparse.ArgumentParser();parser.add_argument('capture');args=parser.parse_args()
directory=Path(args.capture).resolve();meta=json.loads((directory/'metadata.json').read_text());ref=meta.get('camera_reference')
if not ref or not ref.get('complete'):raise SystemExit('No complete camera reference; existing EMG remains available.')
video=(directory/ref['file']).resolve()
if not video.is_relative_to(directory) or hashlib.sha256(video.read_bytes()).hexdigest()!=ref['sha256']:raise SystemExit('Camera reference hash mismatch')
review=directory/'review';review.mkdir(exist_ok=True)
subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-vf','fps=2,scale=320:-1,tile=5x5','-vsync','vfr',str(review/'camera-overview-%03d.jpg')],check=True)
audio=review/'reference-audio.wav'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(audio)],check=True)
rate,samples=wavfile.read(audio);samples=np.asarray(samples,float)/32768;hop=int(rate*.01);n=len(samples)//hop
rms=np.sqrt((samples[:n*hop].reshape(n,hop)**2).mean(axis=1));rise=np.maximum(0,rms-np.r_[rms[0],rms[:-1]])
peaks,_=find_peaks(rise,height=max(.005,float(np.median(rise)+8*np.median(abs(rise-np.median(rise))))),distance=12)
# Media start event is a browser callback, not hardware exposure calibration.
client_start=ref['alignment']['record_client_start'];alignment=ref['alignment'];media_start_capture_t=client_start+alignment['host_offset_seconds']-meta['started_host_uptime']
for line in (directory/'streams.jsonl').open():
 row=json.loads(line)
 event=row.get('camera_event',{})
 if row['kind']=='camera_event' and event.get('event')=='media_started':
  media_start_capture_t=event['client_t']+event['alignment']['host_offset_seconds']-meta['started_host_uptime'];break
report={'kind':'audio_transient_review_hints','verified_snap_times':False,'video_origin_capture_t_estimate':media_start_capture_t,
 'clock_sync_uncertainty_seconds':alignment.get('uncertainty_seconds'),'hardware_audio_video_latency_calibrated':False,
 'candidates':[{'video_seconds':float((i+.5)*.01),'capture_t_estimate':float(media_start_capture_t+(i+.5)*.01),'rms_rise':float(rise[i])} for i in peaks],
 'note':'Claps, speech and impacts can cause peaks. Inspect original video/audio before assigning snap labels. Overviews sample at 2 fps, 25 frames per sheet; inspect the original video at full rate for snaps.'}
(review/'audio-candidates.json').write_text(json.dumps(report,indent=2)+'\n');summary=review_capture(directory)
print(json.dumps({'review_directory':str(review),'camera_frames':summary['camera_observations'],'disagreements':summary['disagreements_at_receipt'],'audio_hints':len(peaks),'labels_automatically_created':False}))
