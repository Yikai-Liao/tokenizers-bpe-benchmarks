#!/usr/bin/env python3
"""Count source SLOC with tokei, excluding BPE test files and cfg(test) items.

The core scope includes the engine and its storage, whether the latter is a
separate crate (Best Multicore) or private engine module (simplified branch).
This is a source-size measurement, not compiled/expanded instruction size.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def mask_noncode(s):
    """Preserve offsets/newlines while masking Rust comments and literals."""
    out = list(s)
    def mask(a,b):
        for j in range(a,b):
            if out[j] != '\n': out[j] = ' '
    i=0
    while i < len(s):
        a=i
        if s.startswith('//',i):
            i=s.find('\n',i)
            if i<0: i=len(s)
        elif s.startswith('/*',i):
            i+=2; depth=1
            while depth:
                if s.startswith('/*',i): depth+=1; i+=2
                elif s.startswith('*/',i): depth-=1; i+=2
                else: i+=1
                if i>len(s): raise ValueError('unterminated comment')
        elif (m:=re.match(r'(?:br|r)(#*)"',s[i:])):
            end='"'+m[1]; i=s.index(end,i+len(m[0]))+len(end)
        elif s[i]=='"':
            i+=1
            while s[i]!='"':
                i+=2 if s[i]=='\\' else 1
            i+=1
        elif (m:=re.match(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'",s[i:])):
            i+=len(m[0])
        else:
            i+=1; continue
        mask(a,i)
    return ''.join(out)


def strip_test(s):
    masked=mask_noncode(s)
    spans=[]
    for m in re.finditer(r'#\[\s*cfg\(\s*(?:test|all\(test,\s*target_pointer_width\s*=\s*[^)]*\))\s*\)\s*\]',masked):
        a=m.start(); i=m.end(); par=bracket=angle=0
        while i<len(masked):
            c=masked[i]
            if c=='(' : par+=1
            elif c==')': par-=1
            elif c=='[': bracket+=1
            elif c==']': bracket-=1
            elif c=='<': angle+=1
            elif c=='>' and masked[i-1]!='-' and angle: angle-=1
            elif not (par or bracket or angle):
                if c in ';,':
                    i+=1; break
                if c=='{':
                    depth=1; i+=1
                    while depth:
                        if masked[i]=='{': depth+=1
                        elif masked[i]=='}': depth-=1
                        i+=1
                    if masked[i:i+1]==';': i+=1
                    break
            i+=1
        spans.append((a,i))
    out=list(s)
    for a,b in spans:
        for i in range(a,b):
            if out[i]!='\n': out[i]=' '
    return ''.join(out)


def count(root):
    bpe=root/'tokenizers/tk-train/src/trainers/bpe'
    groups={'engine':list((bpe/'engine').rglob('*.rs')),
            'trainer_and_word':[bpe/'mod.rs',bpe/'word.rs',bpe/'feed.rs',bpe/'word_counts.rs'],
            'progress':[root/'tokenizers/tk-train/src/progress.rs']}
    old=root/'tokenizers/tk-collections/src'
    if old.exists(): groups['engine']+=list(old.rglob('*.rs'))
    result={}
    with tempfile.TemporaryDirectory(prefix='bpe-sloc-') as temp:
        for group,files in groups.items():
            dest=Path(temp)/group; dest.mkdir()
            retained=[]
            for file in files:
                if file.name in ('tests.rs','reference.rs'): continue
                if not file.exists(): continue
                rel=file.relative_to(root); out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True)
                out.write_text(strip_test(file.read_text()))
                retained.append(str(rel))
            data=json.loads(subprocess.check_output(['tokei','--output','json',str(dest)],text=True))
            result[group]={'code':data['Total']['code'],'comments':data['Total']['comments'],
                           'files':retained,
                           'by_file': {str(Path(report['name']).relative_to(dest)): report['stats']['code']
                                       for report in data.get('Rust', {}).get('reports', [])}}
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    args=p.parse_args()
    print(json.dumps(count(args.source.resolve()),indent=2))
