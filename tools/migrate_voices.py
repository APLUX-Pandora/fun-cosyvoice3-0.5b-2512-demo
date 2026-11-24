#!/usr/bin/env python3
"""Explicit lossless conversion of an old voices.json/NPZ collection to flat voices."""
import argparse,json,re
from pathlib import Path
import numpy as np
from pandora_fun_cosyvoice3_0_5b_2512.cosyvoice3_voices import save_package,validate_package,ROLES

def migrate(source,output):
    source=Path(source).resolve(strict=True);output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise FileExistsError('Choose a new collection; originals are never overwritten')
    catalogue=json.loads((source/'voices.json').read_text())
    ids=[m['id'] for m in catalogue]
    if len(ids)!=len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',v) for v in ids):raise ValueError('Invalid/duplicate legacy voice IDs')
    # Collection publication is atomic as well as each individual package.
    import tempfile,shutil
    from pandora_fun_cosyvoice3_0_5b_2512._cosyvoice3_files import rename_new_directory
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.migrate-voices-',dir=output.parent))
    try:
        for meta in catalogue:
            vid=meta['id'];path=source/'voices'/(vid+'.npz')
            if path.is_symlink() or not path.is_file():raise ValueError('Missing/unsafe legacy pack')
            with np.load(path,allow_pickle=False) as z:arrays={k:z[k].copy() for k in ROLES}
            metadata={**meta,'name':meta.get('name') or vid}
            if 'reference_language' not in metadata:metadata['reference_language']=meta.get('language') or ('zh' if vid.endswith('-zh') else 'en' if vid.endswith('-en') else None)
            preview=source/'voices'/(vid+'.wav')
            save_package(temp/vid,arrays,metadata,preview=preview if preview.is_file() else None)
            _,reloaded,_=validate_package(temp/vid)
            for key in ROLES:
                assert arrays[key].dtype==reloaded[key].dtype and arrays[key].shape==reloaded[key].shape
                assert arrays[key].tobytes()==reloaded[key].tobytes(),key
        rename_new_directory(temp,output);temp=None
    finally:
        if temp is not None:shutil.rmtree(temp)
    return ids
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('source');ap.add_argument('output');a=ap.parse_args()
    print(json.dumps({'migrated':migrate(a.source,a.output),'output':a.output}))
