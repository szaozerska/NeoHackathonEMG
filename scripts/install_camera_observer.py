"""Pin and cache local MediaPipe assets; no user media is uploaded externally."""
import hashlib,json,tarfile,io,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'data/support/vision';root.mkdir(parents=True,exist_ok=True)
version='0.10.21';source=f'https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-{version}.tgz'
blob=urllib.request.urlopen(source).read();archive=tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz');manifest={'version':version,'source':source,'files':{}}
for member in archive.getmembers():
 name=member.name.removeprefix('package/')
 if name in ('vision_bundle.mjs','vision_bundle.mjs.map','LICENSE') or name.startswith('wasm/') and name.endswith(('.js','.wasm')):
  target=root/name;target.parent.mkdir(parents=True,exist_ok=True);payload=archive.extractfile(member).read();target.write_bytes(payload);manifest['files'][name]=hashlib.sha256(payload).hexdigest()
url='https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
payload=urllib.request.urlopen(url).read();(root/'hand_landmarker.task').write_bytes(payload);manifest['model_source']=url;manifest['files']['hand_landmarker.task']=hashlib.sha256(payload).hexdigest()
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(root);print(list(manifest['files']))
