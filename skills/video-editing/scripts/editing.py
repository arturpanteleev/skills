"""Scenario generation, rendering and verification."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
from core import (archive_document,atomic_ffmpeg,colors,crop_filters,display_size,
                  encoding,load_plan,probe,protect_report,resolve,run,seconds,timecode,video,write_json)


def scenario(file):
    f,p,_,_,counts,(_,_,fps),total=load_plan(file)
    rows=[f"# {p.get('title','Видео')} — сценарий",'', '| Ролик | Исходник | Действие | Обоснование |','|---|---|---|---|'];pos=0
    clean=lambda s:str(s).replace('|','/').replace('\n',' ')
    for c,count in zip(p['clips'],counts):
        end=pos+count/fps
        rows.append(f"| {timecode(pos)}–{timecode(end)} | {clean(c['source'])}: {timecode(c['in'])}–{timecode(c['out'])} | {clean(c.get('action',''))} | {clean(c.get('reason',''))} |")
        pos=end
    rows+=['',f'Длительность: {total:.3f} с. Прямые склейки, скорость 1×.','', 'Исходники, crop и решения: `project.json`.']
    if p.get('music'):
        m=p['music'];rows+=['',f"Музыка: {m['path']}, вход {timecode(m.get('start',0))}. Атрибуция: {m.get('credit','указать в music_credit.txt')}."]
    target=f.parent/'сценарий.md';archive_document(target);target.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    return str(target)


def render(args):
    file,p,sources,probes,counts,(w,h,fps),total=load_plan(args.plan);root=file.parent
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.version): raise ValueError('version: letters, digits, underscore or hyphen only')
    folder=root/'parts'/args.version;out=root/'output'/f'video_{args.version}.mp4';snapshot=root/'versions'/args.version
    if folder.exists() or out.exists() or snapshot.exists(): raise ValueError('Version exists; choose a new version')
    preset=args.preset or p.get('output',{}).get('preset','quality');enc=encoding(video(probes[p['clips'][0]['source']]),preset)
    estimated=max(float(video(q).get('bit_rate',q['format'].get('bit_rate',0))) for q in probes.values())
    print(json.dumps({'duration_seconds':total,'source_bitrate_size_reference_MB':round(estimated*total/8/1e6,1),'preset':preset,'note':'Reference, not a size bound; lossless can be much larger'}),flush=True)
    scenario(file);folder.mkdir(parents=True)
    for i,(clip,count) in enumerate(zip(p['clips'],counts),1):
        v=video(probes[clip['source']]);filters=crop_filters(clip.get('crop',p.get('crop')),*display_size(v),w,h)
        filters+=['setpts=PTS-STARTPTS',f'fps={fps}:start_time=0','setsar=1']
        print(f'Rendering part {i}/{len(counts)}',flush=True)
        atomic_ffmpeg(['-ss',clip['in'],'-i',sources[clip['source']],'-map','0:v:0','-frames:v',count,'-an','-vf',','.join(filters)]+enc+['-map_metadata','-1','-movflags','+faststart'],folder/f'part_{i:02}.mp4',root/'analysis'/f'{args.version}_part_{i:02}.log')
        # VFR boundary handling must actually produce the requested number of frames.
        if int(video(probe(folder/f'part_{i:02}.mp4')).get('nb_frames',-1))!=count:
            raise ValueError(f'Part {i} frame count differs from plan; inspect input boundary')
    listing=folder/'concat.txt';listing.write_text(''.join(f"file 'part_{i:02}.mp4'\n" for i in range(1,len(counts)+1)),encoding='utf-8')
    command=['-f','concat','-safe','0','-i',listing]
    if p.get('music'):
        m=p['music'];fade=min(m.get('fade_out',.24),total)
        command+=['-ss',m.get('start',0),'-i',resolve(root,m['path']),'-map','0:v:0','-map','1:a:0','-af',f"afade=t=in:d=0.03,afade=t=out:st={total-fade:.8f}:d={fade:.8f},loudnorm=I={m.get('lufs',-16)}:TP=-1.5:LRA=8",'-c:a','aac','-b:a','256k','-ar','48000']
    else:command+=['-map','0:v:0','-an']
    command+=['-t',f'{total:.8f}','-c:v','copy','-map_metadata','-1','-movflags','+faststart']
    atomic_ffmpeg(command,out,root/'analysis'/f'{args.version}_assembly.log')
    snapshot.mkdir(parents=True);shutil.copy2(file,snapshot/'project.json');shutil.copy2(root/'сценарий.md',snapshot/'сценарий.md')
    # Preserve an overridden CLI preset in the immutable render snapshot.
    snap=json.loads((snapshot/'project.json').read_text(encoding='utf-8'));snap.setdefault('output',{})['preset']=preset;write_json(snapshot/'project.json',snap)
    write_json(root/'analysis'/f'{args.version}_render.json',{'file':str(out),'bytes':out.stat().st_size,'megabytes':round(out.stat().st_size/1e6,1),'preset':preset,'frames':sum(counts),'duration':total,'plan_sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    return str(out)


def verify(args):
    protect_report(args.report,[args.input]+([args.plan] if args.plan else []))
    q=probe(args.input);v=video(q);aud=next((s for s in q['streams'] if s['codec_type']=='audio'),None)
    _,log=run(['ffmpeg','-hide_banner','-v','info','-i',args.input,'-vf','blackdetect=d=0.01:pix_th=0.10:pic_th=0.98','-f','null','-'])
    black=[{'start':float(a),'end':float(b),'duration':float(c)} for a,b,c in re.findall(r'black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)',log)]
    # Some decoders log corruption but return zero. Treat these as failures too.
    errors=[line for line in log.splitlines() if re.search(r'error (?:while|during|decoding)|invalid data found|corrupt(?:ed)? (?:frame|packet)',line,re.I)]
    checks={'full_decode':not errors,'no_black_intervals':not black}
    report={'file':str(Path(args.input).resolve()),'bytes':Path(args.input).stat().st_size,'duration':seconds(q),'video_duration':float(v.get('duration',seconds(q))),'display_size':display_size(v),'frames':v.get('nb_frames'),'color':dict(zip(('primaries','transfer','matrix','range'),colors(v))),'black_intervals':black,'decode_errors':errors,'checks':checks,'limits':['Timing checks do not prove perceptual beat sync or sound quality.','Technical checks do not replace visual review and playback.']}
    if aud:
        report['audio_duration']=float(aud.get('duration',seconds(q)))
        checks['audio_video_ends_within_50ms']=abs(report['audio_duration']-report['video_duration'])<=.05
        checks['audio_video_starts_within_50ms']=abs(float(aud.get('start_time',0))-float(v.get('start_time',0)))<=.05
    if args.plan:
        _,p,_,probes,counts,(w,h,fps),total=load_plan(args.plan)
        checks['expected_duration']=abs(seconds(q)-total)<=1/fps+.005
        checks['expected_dimensions']=display_size(v)==(w,h)
        checks['expected_frame_count']=int(v.get('nb_frames',-1))==sum(counts)
        checks['expected_fps']=abs(float(Fraction(v.get('avg_frame_rate','0/1')))-fps)<.01
        reference=video(probes[p['clips'][0]['source']]);checks['same_color_characteristics']=colors(v)==colors(reference)
        checks['same_pixel_format']=v.get('pix_fmt')==reference.get('pix_fmt')
        checks['expected_audio_presence']=bool(aud)==bool(p.get('music'))
    report['passed']=all(checks.values());write_json(args.report,report)
    Path(args.report).with_suffix('.decode.log').write_text(log,encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise ValueError('Verification found issues; inspect the saved report')
    return str(Path(args.report).resolve())


def reframe(args):
    v=video(probe(args.input));w,h=display_size(v)
    crop=dict(zip(('x','y','width','height'),args.crop));filters=crop_filters(crop,w,h,w,h)+['setsar=1']
    out=Path(args.output).resolve()
    atomic_ffmpeg(['-i',args.input,'-map','0:v:0','-map','0:a?','-vf',','.join(filters)]+encoding(v,args.preset)+['-c:a','copy','-map_metadata','0','-movflags','+faststart'],out,out.with_suffix('.render.log'))
    return str(out)
