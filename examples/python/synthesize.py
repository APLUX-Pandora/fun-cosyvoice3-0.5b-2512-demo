#!/usr/bin/env python3
import argparse
import os
import soundfile as sf
from pandora_fun_cosyvoice3_0_5b_2512 import TTSModel
from _lifecycle import managed_owner, ExampleInterrupted
TEXTS = {'zh': '你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。', 'en': 'Hello, welcome to text-to-speech. Today, we use a clear and natural voice to turn written words into speech you can hear.'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('text',nargs='?')
    ap.add_argument('--models', default=os.environ.get('CV3_MODELS') or 'models')
    ap.add_argument('--voices-dir')
    ap.add_argument('--language',default='zh')
    ap.add_argument('--speaker')
    ap.add_argument('--seed',type=int)
    ap.add_argument('--out',default='speech.wav')
    a=ap.parse_args()
    text=a.text or TEXTS.get(a.language)
    if not text:ap.error('Provide text for this language')
    speaker=a.speaker or ('female-en' if a.language=='en' else 'female-zh')
    with managed_owner(TTSModel.from_pretrained,a.models,voices_dir=a.voices_dir) as (model,stop):
        result=model.synthesize(text,speaker=speaker,language=a.language,seed=a.seed)
        stop.check()
        sf.write(a.out,result.audio,result.sample_rate)
        print(f'{a.out}: {result.duration_s:.2f}s, finish_reason={result.finish_reason}')

if __name__=='__main__':
    try:main()
    except ExampleInterrupted as exc:raise SystemExit(128+exc.signum)
