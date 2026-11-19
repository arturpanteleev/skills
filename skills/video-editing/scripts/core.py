"""Shared local media helpers. No shell commands and no hard-coded media paths."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import subprocess


def run(args):
    p = subprocess.run([str(a) for a in args], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {args[0]}\n{p.stderr.decode(errors='replace')[-4000:]}")
    return p.stdout, p.stderr.decode(errors='replace')


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def protect_report(path, inputs):
    target=Path(path).resolve()
    if target.suffix.lower()!='.json': raise ValueError('Use a .json report filename')
    if target in {Path(item).resolve() for item in inputs}: raise ValueError('Report must not overwrite input media or project data')


def probe(path):
    out, _ = run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path])
    return json.loads(out)


def video(q):
    return next(s for s in q['streams'] if s['codec_type'] == 'video')


def seconds(q):
    return float(q['format']['duration'])


def display_size(v):
    rotation = float(v.get('tags', {}).get('rotate', 0))
    for side in v.get('side_data_list', []):
        if 'rotation' in side: rotation = float(side['rotation'])
    w, h = v['width'], v['height']
    return (h, w) if round(rotation) % 180 else (w, h)


def colors(v):
    return tuple(v.get(k, 'unknown') for k in ('color_primaries','color_transfer','color_space','color_range'))


def finite(n, name, minimum=0):
    if isinstance(n, bool) or not isinstance(n, (int,float)) or not math.isfinite(n) or n < minimum:
        raise ValueError(f'{name}: expected finite number >= {minimum}')
    return n


def resolve(root, path):
    path = Path(path)
    return (root/path).resolve() if not path.is_absolute() else path.resolve()


def crop_filters(crop, w, h, ow, oh):
    result = []
    if crop is not None:
        if set(crop) != {'x','y','width','height'}: raise ValueError('crop requires x, y, width, height only')
        for k,n in crop.items():
            if isinstance(n,bool) or not isinstance(n,int) or n<0 or n%2:
                raise ValueError(f'crop.{k}: use nonnegative even pixels for 4:2:0 alignment')
        x,y,cw,ch = (crop[k] for k in ('x','y','width','height'))
        if min(cw,ch)<2 or x+cw>w or y+ch>h: raise ValueError('Crop exceeds displayed source dimensions')
        result.append(f'crop={cw}:{ch}:{x}:{y}'); w,h=cw,ch
    if w*oh != h*ow: raise ValueError(f'Aspect mismatch: {w}x{h} -> {ow}x{oh}. Choose an explicit crop; stretching is not automatic.')
    if (w,h)!=(ow,oh): result.append(f'scale={ow}:{oh}:flags=lanczos')
    return result


def encoding(v, preset):
    fmt = v.get('pix_fmt',''); hdr=v.get('color_transfer')=='arib-std-b67'
    if v.get('sample_aspect_ratio','1:1') not in ('1:1','0:1','N/A'): raise ValueError('Non-square pixels require explicit geometry handling')
    if v.get('color_transfer') in ('smpte2084','smpte428') or any('DOVI' in str(s) or 'Dolby Vision' in str(s) for s in v.get('side_data_list',[])):
        raise ValueError('PQ/Dolby Vision requires an explicit metadata-preserving workflow; supported here: SDR and HLG')
    if '420' not in fmt or any(n in fmt for n in ('12','16')): raise ValueError('This renderer supports 8/10-bit 4:2:0 only; no implicit bit-depth/chroma reduction')
    high='10' in fmt
    if hdr and not high: raise ValueError('HLG is not tagged as 10-bit; inspect the file')
    hevc=hdr or high
    args=['-c:v','libx265' if hevc else 'libx264','-preset','fast' if preset=='draft' else 'medium','-pix_fmt','yuv420p10le' if high else 'yuv420p','-threads',str(min(os.cpu_count() or 2,4))]
    if hevc:
        params=['pools=4','frame-threads=2','log-level=error']
        if preset=='lossless': params.append('lossless=1')
        else: args+=['-crf','23' if preset=='draft' else '18']
        for key,name in (('color_primaries','colorprim'),('color_transfer','transfer'),('color_space','colormatrix')):
            if v.get(key) not in (None,'unknown','unspecified'): params.append(f'{name}={v[key]}')
        if v.get('color_range') in ('pc','tv'): params.append('range='+('full' if v['color_range']=='pc' else 'limited'))
        args+=['-tag:v','hvc1','-x265-params',':'.join(params)]
    else: args+=['-crf','0' if preset=='lossless' else ('23' if preset=='draft' else '18')]
    for key,flag in (('color_primaries','-color_primaries'),('color_transfer','-color_trc'),('color_space','-colorspace'),('color_range','-color_range')):
        if v.get(key) not in (None,'unknown','unspecified'): args += [flag,v[key]]
    return args


def load_plan(file):
    file=Path(file).resolve()
    if file.suffix.lower()!='.json': raise ValueError('Use a .json project file')
    p=json.loads(file.read_text(encoding='utf-8')); root=file.parent
    if set(p)-{'schema_version','title','date','sources','clips','music','output','crop'}: raise ValueError('Unknown project settings')
    if type(p.get('schema_version')) is not int or p['schema_version']!=1: raise ValueError('schema_version must be integer 1')
    if not isinstance(p.get('clips'),list) or not p['clips']: raise ValueError('Select at least one clip after visual inspection')
    out=p.get('output',{})
    if set(out)-{'width','height','fps','preset'}: raise ValueError('Unknown output settings')
    w,h,fps=out.get('width',1080),out.get('height',1920),out.get('fps',30)
    if any(isinstance(n,bool) or not isinstance(n,int) or n<2 or n%2 for n in (w,h)): raise ValueError('Use positive even output dimensions')
    if isinstance(fps,bool) or not isinstance(fps,int) or not 1<=fps<=120: raise ValueError('fps must be integer 1..120')
    preset=out.get('preset','quality')
    if preset not in ('quality','draft','lossless'): raise ValueError('Unknown export preset')
    sources={key:resolve(root,path) for key,path in p.get('sources',{}).items()}
    probes={key:probe(path) for key,path in sources.items()}; frames=[]; signatures=set(); formats=set()
    for i,c in enumerate(p['clips'],1):
        if set(c)-{'source','in','out','action','reason','crop'}: raise ValueError(f'Unknown settings in clip {i}')
        if c.get('source') not in sources: raise ValueError(f'Unknown source in clip {i}')
        start=finite(c.get('in'),f'clip {i} in'); end=finite(c.get('out'),f'clip {i} out')
        if end<=start or end>seconds(probes[c['source']])+.001: raise ValueError(f'Invalid source interval in clip {i}')
        count=round((end-start)*fps)
        if count<1: raise ValueError(f'Clip {i} is shorter than a frame')
        frames.append(count); v=video(probes[c['source']]);signatures.add(colors(v));formats.add(v.get('pix_fmt'));encoding(v,preset)
        if v.get('sample_aspect_ratio','1:1') not in ('1:1','0:1','N/A'): raise ValueError('Non-square pixel sources require explicit geometry handling')
        crop_filters(c.get('crop',p.get('crop')),*display_size(v),w,h)
    if len(signatures)!=1: raise ValueError('Sources have different color characteristics; choose color management explicitly')
    if len(formats)!=1: raise ValueError('Sources have different pixel formats; choose a bit-depth/chroma policy explicitly')
    total=sum(frames)/fps; m=p.get('music')
    if m:
        if set(m)-{'path','start','bpm','credit','fade_out','lufs'}: raise ValueError('Unknown music settings')
        start=finite(m.get('start',0),'music.start'); mq=probe(resolve(root,m['path']))
        if not any(s['codec_type']=='audio' for s in mq['streams']): raise ValueError('Music has no audio stream')
        if start+total>seconds(mq)+.001: raise ValueError('Music is shorter than selected interval')
        finite(m.get('fade_out',.24),'music.fade_out')
        if finite(m.get('lufs',-16),'music.lufs',-30)>-5: raise ValueError('music.lufs must be -30..-5')
        if m.get('bpm') is not None: finite(m['bpm'],'music.bpm',1)
    return file,p,sources,probes,frames,(w,h,fps),total


def atomic_ffmpeg(args, output, log):
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists(): raise ValueError(f'Output exists; choose a new version: {output}')
    temp=output.with_name(output.stem+'.partial'+output.suffix)
    if temp.exists(): raise ValueError(f'Partial file exists; inspect it or choose a new version: {temp}')
    process=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n']+[str(a) for a in args]+[str(temp)],capture_output=True)
    Path(log).parent.mkdir(parents=True,exist_ok=True);Path(log).write_bytes(process.stderr)
    if process.returncode: raise RuntimeError(f'FFmpeg failed; log: {log}\n{process.stderr.decode(errors="replace")[-2500:]}')
    temp.rename(output)


def timecode(n):
    ms=round(n*1000);hours,rest=divmod(ms,3600000);minutes,rest=divmod(rest,60000);seconds,milli=divmod(rest,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{milli:03}'


def archive_document(target):
    import shutil
    target=Path(target)
    if target.exists():
        archive=target.parent/'versions'/dt.datetime.now(dt.timezone.utc).strftime('documents-%Y%m%dT%H%M%S%fZ')
        archive.mkdir(parents=True);shutil.copy2(target,archive/target.name)
