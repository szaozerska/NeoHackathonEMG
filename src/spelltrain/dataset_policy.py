"""Honor contributor capture rejections before reading signals or using cached features."""
import json
from pathlib import Path


def require_usable_capture(directory):
    directory = Path(directory)
    registry = Path(__file__).resolve().parents[2]/'configs/rejected-captures.json'
    rejected = {v['session_id'] for v in json.loads(registry.read_text())['captures']} if registry.exists() else set()
    meta_path = directory/'metadata.json'
    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if (directory.name in rejected or metadata.get('id') in rejected or
            (directory/'DO_NOT_USE.json').exists() or (directory/'DO_NOT_USE.md').exists() or
            metadata.get('do_not_use') is True or metadata.get('quality_status') == 'rejected' or
            metadata.get('dataset_role') == 'rejected_do_not_use'):
        raise ValueError('DO NOT USE: contributor rejected capture '+directory.name+
                         '; excluded from analysis, training, evaluation and negative baselines.')
