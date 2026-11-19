#!/usr/bin/env python3
"""Portable video workflow CLI. Python 3.10+, ffmpeg and ffprobe on PATH."""
import argparse
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
from core import display_size,load_plan,probe,protect_report,run,video,write_json
from editing import reframe,render,scenario,verify


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    p=sub.add_parser('init');p.add_argument('root');p.add_argument('--date',required=True);p.add_argument('--name',required=True);p.add_argument('--source',action='append',required=True)
    p=sub.add_parser('inspect');p.add_argument('input');p.add_argument('--report',required=True)
    p=sub.add_parser('contacts');p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--start',type=float,default=0);p.add_argument('--end',type=float);p.add_argument('--step',type=float,default=5);p.add_argument('--columns',type=int,default=6)
    p=sub.add_parser('analyze-music');p.add_argument('input');p.add_argument('--output',required=True);p.add_argument('--bpm',type=float)
    for name in ('validate','scenario','render'):
        p=sub.add_parser(name);p.add_argument('plan')
        if name=='render':
            p.add_argument('--version',required=True);p.add_argument('--preset',choices=['quality','draft','lossless'])
    p=sub.add_parser('verify');p.add_argument('input');p.add_argument('--plan');p.add_argument('--report',required=True)
    p=sub.add_parser('reframe');p.add_argument('input');p.add_argument('--crop',nargs=4,type=int,required=True,metavar=('X','Y','W','H'));p.add_argument('--output',required=True);p.add_argument('--preset',choices=['quality','draft','lossless'],default='quality')
    args=parser.parse_args()
    if args.command=='doctor':
        info={'python':sys.version.split()[0],'tools':{n:shutil.which(n) for n in ('ffmpeg','ffprobe')},'optional_python':{n:importlib.util.find_spec(n) is not None for n in ('PIL','numpy','scipy')}}
        if info['tools']['ffmpeg']:
            out,err=run(['ffmpeg','-hide_banner','-encoders']);text=out.decode()+err;info['encoders']={n:n in text for n in ('libx264','libx265')}
        print(json.dumps(info,indent=2));return
    if args.command=='init':
        dt.datetime.strptime(args.date,'%d.%m.%y')
        if not args.name.strip() or any(c in args.name for c in '/\\\0') or args.name in ('.','..'):raise ValueError('Invalid project name')
        root=Path(args.root).resolve()/f'{args.date} {args.name}';files=[Path(s).resolve(strict=True) for s in args.source]
        if any(not f.is_file() for f in files):raise ValueError('Each source must be a file')
        if len({f.name for f in files})!=len(files):raise ValueError('Source basenames collide; give files unique names first')
        if root.exists():raise ValueError(f'Project exists: {root}')
        for folder in ('source','parts','analysis','music','output','versions'):(root/folder).mkdir(parents=True)
        for f in files:shutil.copy2(f,root/'source'/f.name)
        write_json(root/'project.json',{'schema_version':1,'title':args.name,'date':args.date,'sources':{f'source{i}':'source/'+f.name for i,f in enumerate(files,1)},'clips':[],'music':None,'output':{'width':1080,'height':1920,'fps':30,'preset':'quality'}})
        print(root);return
    if args.command=='inspect':
        protect_report(args.report,[args.input]);q=probe(args.input);q['display_dimensions']=display_size(video(q));write_json(args.report,q);print(args.report);return
    if args.command=='validate':
        _,_,_,_,counts,dims,total=load_plan(args.plan);print(json.dumps({'valid':True,'frames':sum(counts),'duration':total,'width_height_fps':dims}));return
    if args.command=='scenario':result=scenario(args.plan)
    elif args.command=='render':result=render(args)
    elif args.command=='verify':result=verify(args)
    elif args.command=='reframe':result=reframe(args)
    elif args.command=='contacts':
        from media_analysis import contacts
        if not all(math.isfinite(n) for n in (args.start,args.step)) or args.end is not None and not math.isfinite(args.end):raise ValueError('Time values must be finite')
        result=contacts(args)
    elif args.command=='analyze-music':
        from media_analysis import analyze_music
        if args.bpm is not None and (not math.isfinite(args.bpm) or args.bpm<=0):raise ValueError('BPM must be positive')
        result=analyze_music(args)
    print(json.dumps({'result':result},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,KeyError,StopIteration,OSError,TypeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);sys.exit(1)
