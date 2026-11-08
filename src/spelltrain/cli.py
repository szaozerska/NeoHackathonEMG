from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import time
from .common import read_json, write_json


def parser():
    root = argparse.ArgumentParser(description="Record, label, train, and evaluate right-hand EMG + Quest spells")
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record", help="Start a new paired recording and local annotation dashboard")
    p.add_argument("--subject", required=True)
    p.add_argument("--session", required=True, help="New directory; existing recordings are never overwritten")
    p.add_argument("--notes", default="")
    p.add_argument("--resume", action="store_true", help="Resume an existing supplemental session without clearing its trials")
    p.add_argument("--training-profile", choices=('baseline','supplemental'), default='baseline')
    p.add_argument("--dataset-role", choices=('development','test'), default='development',
                   help="Reserve an independently recorded session for later frozen-model testing")
    band = p.add_mutually_exclusive_group()
    band.add_argument("--kinesis-env", metavar="ENV_NAME", help="Environment variable containing current loopback SSE URL/token")
    band.add_argument("--kinesis-file", help="Tail the current upstream raw EMG JSONL recording")
    p.add_argument("--adapter", help="JSON field mapping for SSE variant; see configs/")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--web-port", type=int, default=8765)
    p.add_argument("--no-discovery", action="store_true")
    p.add_argument("--emg-only", action="store_true", help="Record band data without opening Quest TCP/discovery services")
    p.add_argument("--model", help="Optional trusted locally trained artifact for live recognition preview")
    p.add_argument("--experimental-snaps", action="store_true", help="Allow unverified weak snap candidates to cast in the live preview")
    p.add_argument("--motion", help="Motion calibration JSON")
    p = sub.add_parser("review", help="Review saved traces and edit annotations locally")
    p.add_argument("--session", required=True)
    p.add_argument("--web-port", type=int, default=8765)
    p = sub.add_parser("inspect-feed", help="Print payload field names/shapes, never token or raw URL")
    p.add_argument("--kinesis-env", required=True)
    p.add_argument("--count", type=int, default=3)
    p = sub.add_parser("quality", help="Report recording coverage, gaps, signal range and label counts")
    p.add_argument("--session", required=True)
    p = sub.add_parser("train", help="Train personalized hand-state and snap detectors")
    p.add_argument("--train", nargs="+", required=True)
    p.add_argument("--validation", nargs="+", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("train-gestures", help="Train v3 hand-state and weak snap models; reuse the frozen shield effort model")
    p.add_argument("--session", required=True)
    p.add_argument("--effort-model", required=True, help="Trusted v3 effort-model.joblib from this unchanged session")
    p.add_argument("--output", required=True)
    p = sub.add_parser("train-effort", help="Train and test shield effort on confirmed open-hand v3 trials; no Quest or snap model")
    p.add_argument("--session", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser('retrain-reviewed', help='Update all EMG models using independently reviewed supplemental references')
    p.add_argument('--features', required=True, help='Trusted local feature cache with source hashes')
    p.add_argument('--reviewed-labels', required=True)
    p.add_argument('--previous-model', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('live-test', help='Run a read-only live EMG gesture tester with a trained bundle')
    p.add_argument('--model', required=True)
    p.add_argument('--kinesis-file', required=True)
    p.add_argument('--auto-source', action='store_true', help='Follow Kinesis active recordings or a configured local feed')
    p.add_argument('--web-port', type=int, default=8765)
    p.add_argument('--display-policy', choices=('v4_feedback','equipment'))
    p = sub.add_parser("calibrate", help="Fit hip and motion thresholds from verified Quest actions")
    p.add_argument("--sessions", nargs="+", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("evaluate", help="Replay both streams on untouched test sessions")
    p.add_argument("--sessions", nargs="+", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--motion")
    p.add_argument("--output", required=True)
    p.add_argument("--development", action="store_true", help="Allow development-session replay; explicitly marked as non-held-out")
    p = sub.add_parser("export", help="Export original samples and poses to portable files")
    p.add_argument("--session", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("demo", help="Generate synthetic paired sessions, train, calibrate and evaluate")
    p.add_argument("--output", default="demo-output")
    return root


def serve(args):
    from .session import Session
    from .recorder import Recorder
    from .models import load_artifact
    review = args.command == "review"
    artifact = load_artifact(args.model) if getattr(args, "model", None) else None
    motion = read_json(args.motion) if getattr(args, "motion", None) else None
    if artifact and artifact["report"]["subject"] != args.subject:
        raise ValueError("Model subject differs from recording subject")
    if motion and motion.get("subject") not in (None, args.subject):
        raise ValueError("Motion calibration subject differs from recording subject")
    if not review and args.emg_only and not (args.kinesis_env or args.kinesis_file):
        raise ValueError("EMG-only mode requires --kinesis-file or --kinesis-env")
    resuming = getattr(args, 'resume', False)
    if resuming:
        session = resume_supplemental(args.session, args.subject, args.kinesis_file, args.emg_only)
    else:
        session = Session(args.session, getattr(args,"subject",None), getattr(args,"notes",""), create=not review)
    if not review and not resuming:
        session.meta["mode"] = "emg_only" if args.emg_only else "paired"
        session.meta['training_profile'] = args.training_profile
        session.meta['dataset_role'] = args.dataset_role
        if args.kinesis_file:
            session.meta["band_file"] = str(Path(args.kinesis_file).resolve())
        write_json(session.directory / "metadata.json", session.meta)
    recorder = Recorder(session, artifact, motion, review,
                        experimental_snaps=getattr(args, 'experimental_snaps', False))
    def interrupt(*_):
        recorder.stop.set()
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if not review:
            recorder.spawn(recorder.worker)
            if not args.emg_only:
                port = recorder.start_tcp(args.host, args.port)
                if not args.no_discovery:
                    recorder.spawn(lambda: recorder.beacon(port))
            if args.kinesis_env:
                url = os.environ.get(args.kinesis_env)
                if not url:
                    raise ValueError("Kinesis URL environment variable is empty")
                from urllib.parse import urlsplit
                parts = urlsplit(url)
                if parts.scheme != "http" or parts.hostname not in ("127.0.0.1","localhost","::1"):
                    raise ValueError("Kinesis SSE must use loopback HTTP")
                recorder.start_band(url=url, adapter=read_json(args.adapter) if args.adapter else None)
            elif args.kinesis_file:
                recorder.start_band(filename=args.kinesis_file)
            else:
                print("No band source configured; Quest-only recording. Add --kinesis-file or --kinesis-env for paired training.", flush=True)
            if args.emg_only:
                print("EMG-only mode: Quest is not required. Waiting for the band source.", flush=True)
            else:
                print(f"Quest TCP listening on {args.host}:{port}. Allow your Mac firewall and use the Mac LAN IP in Unity.", flush=True)
        web_port = recorder.start_web(args.web_port)
        print(f"Training dashboard: http://127.0.0.1:{web_port} (Ctrl-C to finish)", flush=True)
        while not recorder.stop.wait(.25):
            pass
    finally:
        recorder.close()


def resume_supplemental(directory, subject, band_file, emg_only):
    from collections import Counter
    from .common import json_lines
    from .session import Session
    from .supplemental import LABEL_FILE, PROTOCOL, protocol
    directory = Path(directory)
    meta = read_json(directory/'metadata.json')
    if meta.get('training_profile') != 'supplemental' or meta.get('subject') != subject:
        raise ValueError('Resume requires the same subject and an existing supplemental session')
    if meta.get('incomplete') or meta.get('synthetic'):
        raise ValueError('Cannot resume an incomplete or synthetic recording')
    if not emg_only or meta.get('mode') != 'emg_only' or not band_file or str(Path(band_file).resolve()) != meta.get('band_file'):
        raise ValueError('Resume with the same EMG-only band recording path')
    if time.monotonic() < meta['origin_monotonic']:
        raise ValueError('Session clock is from a prior boot; start a separate session')
    results = read_json(directory/LABEL_FILE) if (directory/LABEL_FILE).exists() else []
    if any(r.get('protocol') != PROTOCOL for r in results):
        raise ValueError('Unexpected labels in supplemental session')
    if len({r['motion'] for r in results if r.get('confirmed') is True}) >= len(protocol(meta['id'])):
        raise ValueError('This session is complete; start a new one')
    counts = Counter(row['kind'] for row in json_lines(directory/'streams.jsonl'))
    session = Session(directory, create=False)
    session.created_here = True
    session.counts = counts
    session.meta['recording_closed'] = False
    write_json(directory/'metadata.json', session.meta)
    return session


def export_session(directory, output):
    import numpy as np
    from .session import load_session
    meta, ann, rows = load_session(directory)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    samples, timestamps = [], []
    fs = 2048
    for row in rows:
        if row["kind"] == "emg":
            samples.extend(row["samples"])
            timestamps.extend(row["t"]-np.arange(len(row["samples"])-1,-1,-1)/fs)
    np.savez_compressed(output/"emg.npz", samples=np.asarray(samples,dtype=np.uint16).reshape(-1,8),
                        t=np.asarray(timestamps), sample_rate=fs)
    with (output/"quest.jsonl").open("w") as stream:
        for row in rows:
            if row["kind"] == "pose":
                stream.write(json.dumps(row)+"\n")
    write_json(output/"metadata.json",meta)
    write_json(output/"annotations.json",ann)
    return {"output":str(output),"samples":len(samples)}


def main():
    args = parser().parse_args()
    try:
        result = None
        if args.command == 'live-test':
            from .models import load_artifact
            from .live_test import LiveTester
            tester = LiveTester(load_artifact(args.model), args.kinesis_file, display_policy=args.display_policy, auto_source=args.auto_source)
            signal.signal(signal.SIGINT, lambda *_: tester.stop.set())
            signal.signal(signal.SIGTERM, lambda *_: tester.stop.set())
            try:
                port = tester.start(args.web_port)
                print(f'Live model tester: http://127.0.0.1:{port}', flush=True)
                print('Kinesis raw recording path: '+tester.band_file, flush=True)
                while not tester.stop.wait(.25):
                    pass
            finally:
                tester.close()
        elif args.command in ("record", "review"):
            serve(args)
        elif args.command == "quality":
            from .evaluation import quality
            result = quality(args.session)
        elif args.command == "train":
            from .models import fit_models
            result = fit_models(args.train, args.validation, args.output)
        elif args.command == "train-effort":
            from .effort import fit_effort
            report = fit_effort(args.session, args.output)
            result = {"output": str(Path(args.output).resolve()), "selected_candidate": report['selected_candidate'],
                      "held_out_test": report['test'], "limitations": report['limitations']}
        elif args.command == "train-gestures":
            from .gestures import train_gestures
            report = train_gestures(args.session, args.output, args.effort_model)
            result = {"output": str(Path(args.output).resolve()),
                      "hand_state_test": report['hand_state']['test'],
                      "fireball_clip_test": report['fireball_snap']['test'],
                      "fireball_causal_candidate_test": report['fireball_snap']['causal_candidate_test'],
                      "shield_effort_test": report['shield_effort']['test'],
                      "limitations": report['limitations']}
        elif args.command == 'retrain-reviewed':
            from .retraining import retrain_reviewed
            report = retrain_reviewed(args.features, args.reviewed_labels, args.previous_model, args.output)
            result = {'output':str(Path(args.output).resolve()),
                      'state_segments':report['hand_state']['test_reviewed_segments'],
                      'effort':report['shield_effort']['test'], 'snap_events':report['fireball_snap']['test'],
                      'limitations':report['limitations']}
        elif args.command == "calibrate":
            from .evaluation import calibrate_motion
            result = calibrate_motion(args.sessions, args.output)
        elif args.command == "evaluate":
            from .models import load_artifact
            artifact = load_artifact(args.model)
            if artifact.get('task') == 'v3_gesture_bundle':
                from .gestures import evaluate_gestures
                if args.motion:
                    raise ValueError('V3 bundle evaluation scores EMG only; --motion is for legacy paired replay')
                result = evaluate_gestures(args.sessions, artifact, args.output, args.development)
            else:
                from .evaluation import evaluate
                result = evaluate(args.sessions, artifact, args.output,
                                  read_json(args.motion) if args.motion else None, args.development)
        elif args.command == "export":
            result = export_session(args.session,args.output)
        elif args.command == "inspect-feed":
            import urllib.request
            from urllib.parse import urlsplit
            from .feeds import sse_events
            url=os.environ.get(args.kinesis_env,"")
            if urlsplit(url).hostname not in ("127.0.0.1","localhost","::1"):
                raise ValueError("Set a loopback Kinesis feed URL in the requested environment variable")
            def describe(value):
                if isinstance(value,dict):return {k:describe(v) for k,v in value.items() if not any(secret in k.lower() for secret in ("token","secret","password"))}
                if isinstance(value,list):return {"length":len(value),"item":describe(value[0]) if value else None}
                return type(value).__name__
            with urllib.request.urlopen(url,timeout=10) as stream:
                for i,(event,payload) in enumerate(sse_events(stream)):
                    print(json.dumps({"event":event,"shape":describe(payload)}))
                    if i+1>=args.count:break
        elif args.command == "demo":
            from .synthetic import make_session
            from .models import fit_models, load_artifact
            from .evaluation import calibrate_motion, evaluate
            base=Path(args.output)
            base.mkdir(parents=True,exist_ok=False)
            paths=[str(make_session(base/f"session-{i}",seed=i)) for i in range(1,5)]
            print("Generated synthetic fixtures. Training software wiring only; no hardware accuracy claim.",flush=True)
            fit_models(paths[:2],paths[2:3],base/"model")
            calibrate_motion(paths[:2],base/"motion.json")
            result=evaluate(paths[3:],load_artifact(base/"model"),base/"evaluation",read_json(base/"motion.json"))
            print(f"Artifacts saved in {base}",flush=True)
        if result is not None:
            print(json.dumps(result,indent=2,allow_nan=False))
    except (ValueError, KeyError, OSError) as exc:
        # URLs and feed secrets never enter our error strings.
        if args.command == "inspect-feed":
            raise SystemExit("Feed inspection failed; check the loopback URL/token and payload format") from None
        raise SystemExit(str(exc)) from None
