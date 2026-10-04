from __future__ import annotations
import hashlib, json, math, random, struct, wave
from pathlib import Path
from .domain import CompositionRequest

SAMPLE_RATE=22050
ENGINE_ID="Local Procedural Composer v1 reauthored"
BASE_FREQ={"C":261.6256,"D":293.6648,"E":329.6276,"F":349.2282,"G":391.9954,"A":440.0,"B":493.8833}
STYLE_INTERVALS={
    "ambient":[0,7,12,16],
    "pop":[0,4,7,12],
    "cinematic":[0,3,7,10],
    "lofi":[0,3,7,14],
    "electronic":[0,7,10,12],
}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def _freq(base:float,semitones:int)->float:
    return base*(2.0**(semitones/12.0))

def render_wav(req:CompositionRequest,out:Path)->dict:
    req=req.validate()
    out.parent.mkdir(parents=True,exist_ok=True)
    rng=random.Random(req.seed)
    base=BASE_FREQ[req.key]
    intervals=STYLE_INTERVALS[req.style]
    frames=req.duration_seconds*SAMPLE_RATE
    beat=max(1,int(SAMPLE_RATE*60.0/req.bpm))
    with wave.open(str(out),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        buf=bytearray()
        for i in range(frames):
            t=i/SAMPLE_RATE
            step=(i//beat)%len(intervals)
            chord=intervals[step]
            f1=_freq(base,chord)
            f2=_freq(base,chord+7)
            f3=_freq(base,chord+12)
            # deterministic amplitude envelope and tiny seed-bound timbre modulation
            phase=(i%beat)/beat
            env=min(1.0,phase*6.0)*min(1.0,(1.0-phase)*2.2)
            mod=0.92+0.08*math.sin(2*math.pi*(0.2+(req.seed%9)/30.0)*t)
            x=(math.sin(2*math.pi*f1*t)+0.55*math.sin(2*math.pi*f2*t)+0.3*math.sin(2*math.pi*f3*t))/1.85
            x+=0.02*(rng.random()-0.5)
            sample=int(max(-1.0,min(1.0,x*env*mod*0.6))*32767)
            buf+=struct.pack("<h",sample)
            if len(buf)>=65536:
                w.writeframesraw(buf); buf.clear()
        if buf:
            w.writeframesraw(buf)
    with wave.open(str(out),"rb") as w:
        integrity={
            "channels":w.getnchannels(),
            "sample_width":w.getsampwidth(),
            "sample_rate":w.getframerate(),
            "frames":w.getnframes(),
            "duration_seconds":w.getnframes()/w.getframerate(),
        }
    meta={
        "status":"PASS",
        "engine_id":ENGINE_ID,
        "cloud_ai_claim":False,
        "request":req.to_dict(),
        "audio":integrity,
        "wav_sha256":sha256(out),
        "wav_bytes":out.stat().st_size,
    }
    return meta

def deterministic_check(req:CompositionRequest,tmp:Path)->dict:
    a=tmp/"a.wav"; b=tmp/"b.wav"
    ma=render_wav(req,a); mb=render_wav(req,b)
    return {"status":"PASS" if ma["wav_sha256"]==mb["wav_sha256"] else "FAIL",
            "sha_a":ma["wav_sha256"],"sha_b":mb["wav_sha256"]}
