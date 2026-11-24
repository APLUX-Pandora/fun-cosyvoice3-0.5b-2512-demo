"""Versioned prepared-voice file I/O; no feature extraction or model execution."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import numpy as np
from ._cosyvoice3_files import rename_new_directory

MODEL_ID = 'FunAudioLLM/Fun-CosyVoice3-0.5B-2512'
CONDITIONING = 'cosyvoice3-reference-v1'
ROLES = ('prompt_text_ids','prompt_text_rows','llm_prompt_token','flow_prompt_token','prompt_feat','embedding')


def _regular(root, name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.','..'):
        raise ValueError('Voice payload must be a flat relative filename')
    p=root/name
    if p.is_symlink() or not p.is_file():raise ValueError('Missing or unsafe voice file: '+name)
    return p


def validate_package(path):
    root=Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (root,*root.parents)) or not root.is_dir():
        raise ValueError('Voice package must be a real directory without symlinks')
    manifest=_regular(root,'voice.json')
    if manifest.stat().st_size>1048576:raise ValueError('Oversized voice manifest')
    meta=json.loads(manifest.read_text(encoding='utf-8'))
    if type(meta.get('format_version')) is not int or meta['format_version']!=1:raise ValueError('Unsupported voice format_version')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',meta.get('id','')):raise ValueError('Invalid voice ID')
    if not isinstance(meta.get('name'),str) or not meta['name'].strip():raise ValueError('Missing voice name')
    if meta.get('model_id')!=MODEL_ID or meta.get('conditioning_version')!=CONDITIONING:raise ValueError('Incompatible model/conditioning')
    files=meta.get('files',{})
    if set(files)!=set(ROLES):raise ValueError('Voice requires exactly six conditioning roles')
    arrays={};digests=[]
    for role in ROLES:
        spec=files[role];p=_regular(root,spec.get('path'))
        if p.suffix!='.npy' or not 0<p.stat().st_size<=8*1024*1024:raise ValueError('Invalid tensor file size/format')
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if spec.get('sha256')!=digest:raise ValueError('Voice digest mismatch: '+role)
        a=np.load(p,allow_pickle=False)
        dtype=np.dtype('<i4' if role in ('prompt_text_ids','llm_prompt_token','flow_prompt_token') else '<f4')
        if a.dtype!=dtype or a.dtype.str!=spec.get('dtype') or list(a.shape)!=spec.get('shape') or not a.flags.c_contiguous:
            raise ValueError('Voice dtype/shape/order mismatch: '+role)
        if not np.isfinite(a).all():raise ValueError('Nonfinite voice tensor: '+role)
        arrays[role]=a;digests.append(digest)
    t=arrays['prompt_text_ids'];s=arrays['llm_prompt_token'];f=arrays['flow_prompt_token']
    if t.ndim!=1 or not 0<t.size<=1024 or np.any(t<0) or np.any(t>=151936):raise ValueError('Invalid text token IDs')
    if arrays['prompt_text_rows'].shape!=(t.size,896):raise ValueError('Invalid reference text rows')
    if s.ndim!=1 or f.ndim!=1 or not 0<s.size<=250 or not np.array_equal(s,f) or np.any(s<0) or np.any(s>=6561):raise ValueError('Invalid reference speech tokens')
    if arrays['prompt_feat'].shape!=(2*s.size,80) or arrays['embedding'].shape!=(192,):raise ValueError('Invalid reference feature dimensions')
    if meta.get('preview') is not None:_regular(root,meta['preview'])
    identity=hashlib.sha256(json.dumps([MODEL_ID,CONDITIONING,digests],separators=(',',':')).encode()).hexdigest()
    return meta,arrays,identity


def save_package(path, arrays, metadata, *, preview=None):
    """Validate a temporary sibling, then publish without replacing any existing path."""
    dst=Path(path).expanduser().absolute()
    if dst.exists() or dst.is_symlink():raise FileExistsError(str(dst))
    dst.parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='.voice-',dir=dst.parent))
    try:
        meta={k:v for k,v in metadata.items() if k not in ('files','preview','format_version','model_id','conditioning_version')}
        meta.update(format_version=1,model_id=MODEL_ID,conditioning_version=CONDITIONING,files={})
        for role in ROLES:
            a=np.asarray(arrays[role]);p=folder/(role+'.npy');np.save(p,a,allow_pickle=False)
            meta['files'][role]={'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'dtype':a.dtype.str,'shape':list(a.shape)}
        if preview is not None:
            shutil.copyfile(preview,folder/'preview.wav');meta['preview']='preview.wav'
        (folder/'voice.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        validate_package(folder);rename_new_directory(folder,dst);folder=None
        return dst
    finally:
        if folder is not None:shutil.rmtree(folder)


def collection(path):
    root=Path(path).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():raise ValueError('Invalid voice collection directory')
    if (root/'voices.json').exists():raise ValueError('Legacy catalogue: run tools/migrate_voices.py explicitly; originals are preserved')
    for p in sorted(root.iterdir()):
        if p.name.startswith('.'):continue
        if p.is_dir() or p.is_symlink():
            validate_package(p)
            yield p


def builtin_collection():
    """Resolve the built-in collection declared by this model SDK's profile."""
    from importlib.resources import files
    assets=Path(str(files('pandora_fun_cosyvoice3_0_5b_2512._cosyvoice3_runtime')/'assets'))
    profile=json.loads((assets/'tts-model.json').read_text())
    if profile.get('model_id')!=MODEL_ID or profile.get('builtin_voices')!='voices':raise ValueError('Unsupported builtin voice declaration')
    return assets/profile['builtin_voices']
