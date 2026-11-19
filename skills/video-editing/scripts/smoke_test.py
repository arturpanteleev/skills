#!/usr/bin/env python3
"""Exercise the real CLI in a temporary workspace. Optional: --hdr-source ORIGINAL --music TRACK."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--workdir');ap.add_argument('--hdr-source');ap.add_argument('--music');a=ap.parse_args()
    root=Path(a.workdir).resolve() if a.workdir else Path(tempfile.mkdtemp(prefix='video-skill-test-'))
    root.mkdir(parents=True,exist_ok=True);script=Path(__file__).with_name('video.py');results=[]
    def command(args,fail=False):
        p=subprocess.run([str(x) for x in args],capture_output=True)
        if (p.returncode==0)==fail:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
        return p.stdout.decode(errors='replace')
    def cli(*args,fail=False):return command([sys.executable,script,*args],fail=fail)
    fixture=root/'fixture sdr.mp4'
    command(['ffmpeg','-v','error','-n','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv',fixture])
    cli('init',root,'--date','19.11.26','--name','smoke project','--source',fixture)
    project=root/'19.11.26 smoke project';plan=project/'project.json';p=json.loads(plan.read_text())
    p['clips']=[{'source':'source1','in':.2,'out':1.4,'action':'test part A','reason':'actual boundary test'},{'source':'source1','in':1.5,'out':2.7,'action':'test part B','reason':'actual concat test'}]
    p['output'].update(width=320,height=180)
    if a.music:p['music']={'path':str(Path(a.music).resolve()),'start':34.55,'bpm':100}
    plan.write_text(json.dumps(p),encoding='utf-8')
    cli('inspect',fixture,'--report',project/'analysis/source.json');cli('validate',plan)
    cli('scenario',plan);cli('render',plan,'--version','smoke')
    output=project/'output/video_smoke.mp4';cli('verify',output,'--plan',plan,'--report',project/'analysis/verification.json')
    cli('render',plan,'--version','smoke',fail=True);results+=['SDR render/concat/verify: 72 frames, 2.4s','existing version rejected']
    bad=dict(p);bad['clips']=[{'source':'source1','in':0,'out':300}];invalid=project/'invalid.json';invalid.write_text(json.dumps(bad));cli('validate',invalid,fail=True);results.append('out-of-range clip rejected')
    cli('reframe',output,'--crop','0','0','288','162','--output',project/'output/reframe.mp4');cli('verify',project/'output/reframe.mp4','--report',project/'analysis/reframe.json');results.append('reframe with preserved dimensions')
    bad=dict(p);bad['crop']={'x':0,'y':0,'width':300,'height':170};invalid.write_text(json.dumps(bad));cli('validate',invalid,fail=True);results.append('aspect-ratio mismatch rejected')
    if a.hdr_source:
        hdr=root/'hdr project';hdr.mkdir();hp=hdr/'project.json'
        p={'schema_version':1,'title':'HLG smoke','sources':{'hdr':str(Path(a.hdr_source).resolve())},'clips':[{'source':'hdr','in':24.6,'out':25.4},{'source':'hdr','in':60.8,'out':61.6},{'source':'hdr','in':69.6,'out':70.4}],'crop':{'x':0,'y':0,'width':1008,'height':1792},'output':{'width':360,'height':640,'fps':30,'preset':'quality'},'music':None}
        if a.music:p['music']={'path':str(Path(a.music).resolve()),'start':34.55,'bpm':100}
        hp.write_text(json.dumps(p));cli('render',hp,'--version','hlg');cli('verify',hdr/'output/video_hlg.mp4','--plan',hp,'--report',hdr/'analysis/verification.json');results.append('real rotated HLG: 3 parts, crop, 10-bit color tags, 72 frames')
        cli('contacts',a.hdr_source,'--output',hdr/'analysis/contact.jpg','--start','24.6','--end','27','--step','.8');results.append('exact-seek contact sheet')
    if a.music:
        cli('analyze-music',a.music,'--output',root/'music_analysis.json','--bpm','100');results.append('music attack/tempo/energy analysis')
    report={'passed':True,'checks':results,'workdir':str(root)};(root/'smoke_results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
