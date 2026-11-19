"""Optional contact sheets and audio features. Lazy imports keep the core dependency-free."""
import io
import math
from pathlib import Path
from core import display_size,probe,protect_report,run,seconds,timecode,video,write_json


def contacts(args):
    try:from PIL import Image,ImageDraw
    except ImportError:raise ValueError('Install Pillow in a venv; see references/portability.md')
    q=probe(args.input);end=min(args.end if args.end is not None else seconds(q),seconds(q))
    if args.step<=0 or args.start<0 or args.start>=end:raise ValueError('Invalid contact-sheet time range')
    if not 1<=args.columns<=12:raise ValueError('columns must be 1..12')
    times=[];t=args.start
    while t<end-.001:
        times.append(round(t,6));t+=args.step
        if len(times)>120:raise ValueError('More than 120 frames; narrow the range or increase step')
    output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if output.suffix.lower() not in ('.jpg','.jpeg','.png') or output==Path(args.input).resolve():raise ValueError('Choose a new JPEG/PNG filename, distinct from source media')
    w,h=display_size(video(q));thumb_w=180;thumb_h=round(180*h/w);cell_h=thumb_h+30;pages=[]
    planned=[output] if len(times)<=36 else [output.with_name(output.stem+f'_{i:02}'+output.suffix) for i in range(1,math.ceil(len(times)/36)+1)]
    if any(path.exists() for path in planned) or output.with_suffix('.json').exists():raise ValueError('Contact output exists; choose a new filename')
    for offset,path in zip(range(0,len(times),36),planned):
        batch=times[offset:offset+36];cols=min(args.columns,len(batch));sheet=Image.new('RGB',(cols*200,math.ceil(len(batch)/cols)*cell_h),(24,24,24));draw=ImageDraw.Draw(sheet)
        for j,t in enumerate(batch):
            data,_=run(['ffmpeg','-v','error','-ss',t,'-i',args.input,'-frames:v','1','-vf',f'scale={thumb_w}:{thumb_h}','-f','image2pipe','-c:v','mjpeg','-'])
            image=Image.open(io.BytesIO(data));x=(j%cols)*200+10;y=(j//cols)*cell_h;sheet.paste(image,(x,y));draw.text((x,y+thumb_h+4),timecode(t),fill='white')
        sheet.save(path);pages.append(str(path))
    write_json(output.with_suffix('.json'),{'source':str(Path(args.input).resolve()),'timestamps_seconds':times,'pages':pages,'note':'Requested seek times, nearest available frame. JPEG is for composition, not HDR color assessment.'})
    return pages


def analyze_music(args):
    protect_report(args.output,[args.input])
    try:
        import numpy as np
        from scipy import signal
    except ImportError:raise ValueError('Install NumPy and SciPy in a venv; see references/portability.md')
    sr=22050;raw,_=run(['ffmpeg','-v','error','-i',args.input,'-vn','-ac','1','-ar',sr,'-f','f32le','-']);x=np.frombuffer(raw,dtype='<f4')
    if len(x)<sr:raise ValueError('Music is shorter than one second')
    _,t,z=signal.stft(x,sr,nperseg=1024,noverlap=768);mag=np.abs(z);flux=np.maximum(np.diff(mag,axis=1),0).sum(axis=0);step=256/sr
    corr=signal.correlate(flux-flux.mean(),flux-flux.mean(),method='fft')[len(flux)-1:];lags=np.arange(len(corr))*step;valid=np.where((lags>=60/150)&(lags<=60/75))[0]
    if np.max(flux)<1e-8:raise ValueError('No reliable attacks detected; audio may be silent')
    measured=float(60/lags[valid[np.argmax(corr[valid])]]);chosen=args.bpm or measured
    peaks,_=signal.find_peaks(flux,distance=max(1,int(.15/step)),prominence=max(float(np.std(flux)*.5),1e-9));windows=[]
    for start in np.arange(0,len(x)/sr,2.4):
        y=x[int(start*sr):int((start+2.4)*sr)];windows.append({'start':round(float(start),3),'rms':round(float(np.sqrt(np.mean(y*y))),6)})
    write_json(args.output,{'source':str(Path(args.input).resolve()),'measured_bpm_approx':measured,'reference_bpm':chosen,'reference_bpm_supplied':args.bpm is not None,'beat_period_seconds':60/chosen,'attack_candidates_seconds':t[1:][peaks].round(5).tolist(),'energy_windows':windows,'limitations':'Spectral attacks are not all beats; tempo may be half/double. Energy alone does not prove a climax; listen and check phrases.'})
    return str(Path(args.output).resolve())
