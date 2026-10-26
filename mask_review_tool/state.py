"""Portable content binding for review records; absolute paths are never identities."""
from datetime import datetime,timezone
import hashlib
import json
import shutil


def atomic_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def signature(raw,masks,key):
    return dict(raw=hashlib.sha256(raw[key].read_bytes()).hexdigest(),mask=hashlib.sha256(masks[key].read_bytes()).hexdigest() if key in masks else None)


def load_reviews(output,fingerprints):
    path=output/'reviews.json';binding=output/'source_fingerprints.json'
    reviews=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    previous=json.loads(binding.read_text(encoding='utf-8')).get('sources',{}) if binding.exists() else None
    if not isinstance(reviews,dict):raise ValueError('reviews.json must be an object')
    warnings=[];rejected={};active={}
    for key,record in reviews.items():
        if key not in fingerprints:rejected[key]=dict(reason='image_missing',record=record)
        elif previous is not None and previous.get(key)!=fingerprints[key]:rejected[key]=dict(reason='source_changed',record=record,old=previous.get(key),current=fingerprints[key])
        else:active[key]=record
    legacy=bool(reviews) and previous is None
    if legacy or rejected:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copy2(path,output/f'reviews.backup.{stamp}.json')
        if rejected:atomic_json(output/f'reviews.quarantine.{stamp}.json',rejected)
        atomic_json(path,active)
        if legacy:warnings.append('旧形式の確認結果を現在の画像に対応付けました。元JSONはbackupに保持しています。過去の画像との同一性は検証できません。')
        if rejected:warnings.append(f'{len(rejected)}件の確認結果を隔離しました（画像の変更・削除）。元の記録はquarantine/backup JSONで保持しています。')
    atomic_json(binding,dict(version=1,sources=fingerprints))
    return active,warnings
