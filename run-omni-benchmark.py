#!/usr/bin/env python3
"""Explicit opt-in runner for the image's Omni diffusion benchmark. No service changes."""
import argparse
import datetime
import hashlib
import json
import pathlib
import shutil
import subprocess
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--execute', action='store_true', help='Required to send generation requests')
p.add_argument('--group', choices=['16x9-10s', '16x9-15s', '4x3-10s', '4x3-15s', 'all'], default='16x9-10s')
p.add_argument('--runs', type=int, default=5, help='Measured requests per shape, 1..10')
a = p.parse_args()
if not a.execute:
    print('Prepared only. Add --execute to generate. Groups: 16x9-10s, 16x9-15s, 4x3-10s, 4x3-15s, all. Default: 5 measured requests + 1 warmup per shape.')
    raise SystemExit(0)
if not 1 <= a.runs <= 10:
    p.error('--runs must be in 1..10')

def command(args, **kw):
    return subprocess.run(args, check=True, **kw)

info = json.loads(command(['docker', 'inspect', 'minimax-h3'], capture_output=True, text=True).stdout)[0]
cmd = info['Config']['Cmd']
assert info['State']['Running'], 'Service is stopped'
for flag, expected in [('--num-gpus', '8'), ('--tensor-parallel-size', '8'), ('--dlo-resident-layers', '50')]:
    assert cmd[cmd.index(flag)+1] == expected, f'Unexpected {flag}'
assert 'NCCL_P2P_LEVEL=SYS' in info['Config']['Env']
assert '--task-type' not in cmd, 'Expected combined baseline'
command(['curl', '--fail', '--max-time', '10', '-sS', 'http://127.0.0.1:8000/health'])
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out = ROOT/'out'/('omni-tp8-r50-'+stamp)
out.mkdir(parents=True)
(out/'container.json').write_text(json.dumps(info, indent=2))
source = '/app/vllm-omni/benchmarks/diffusion'
command(['docker', 'cp', 'minimax-h3:'+source, str(out/'diffusion')])
backend = out/'diffusion'/'backends.py'
original = backend.read_text()
assert 'timeout_seconds = 600.0' in original, 'Review benchmark polling timeout before running'
backend.write_text(original.replace('timeout_seconds = 600.0', 'timeout_seconds = 3600.0'))
client = out/'diffusion'/'diffusion_benchmark_serving.py'
client_original = client.read_text()
start = client_original.index('        import pandas as pd', client_original.index('class CustomDataset'))
end = client_original.index('        print(f"Loaded', start)
client.write_text(client_original[:start] + '''        with open(self.dataset_path, encoding="utf-8") as stream:
            self.data = [json.loads(line) for line in stream if line.strip()]
        if not self.data or any("prompt" not in row for row in self.data):
            raise ValueError("Each JSONL row must contain prompt")
''' + client_original[end:])
(out/'dataset-loader-patch.json').write_text(json.dumps({'change':'Read fixed prompt/seed JSONL using stdlib instead of optional pandas; request and timing logic unchanged','original_sha256':hashlib.sha256(client_original.encode()).hexdigest()},indent=2))
(out/'client-patch.json').write_text(json.dumps({'change':'Video polling deadline 600s -> 3600s; otherwise image benchmark unchanged', 'original_backend_sha256':hashlib.sha256(original.encode()).hexdigest()}, indent=2))
shutil.copyfile(ROOT/'benchmark-vbench10.jsonl', out/'coverage.jsonl')
groups = {'16x9-10s':(1344,768,240,'16:9'), '16x9-15s':(1344,768,360,'16:9'),
          '4x3-10s':(1024,768,240,'4:3'), '4x3-15s':(1024,768,360,'4:3')}
selected = list(groups) if a.group == 'all' else [a.group]
stop = threading.Event()
phase = {'group':None,'phase':'idle'}
memory_samples = []
def monitor():
    with (out/'host-memory.jsonl').open('w') as f:
        while not stop.is_set():
            mem = dict(line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())
            stats = subprocess.run(['docker','stats','--no-stream','--format','{{json .}}','minimax-h3'], capture_output=True,text=True)
            kb = {k:int(v.split()[0]) for k,v in mem.items()}
            sample={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), **phase,
                    'system_total_bytes':kb['MemTotal']*1024,
                    'system_used_bytes':(kb['MemTotal']-kb['MemAvailable'])*1024,
                    'system_available_bytes':kb['MemAvailable']*1024,
                    'system_free_bytes':kb['MemFree']*1024,
                    'system_cache_bytes':(kb.get('Buffers',0)+kb.get('Cached',0)+kb.get('SReclaimable',0))*1024,
                    'system_shmem_bytes':kb.get('Shmem',0)*1024,
                    'swap_used_bytes':(kb.get('SwapTotal',0)-kb.get('SwapFree',0))*1024,
                    'meminfo':mem,'docker_stats':stats.stdout.strip()}
            memory_samples.append(sample)
            f.write(json.dumps(sample)+'\n'); f.flush()
            stop.wait(2)
gpu_file = (out/'gpu.csv').open('w')
gpu = subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,index,memory.used,utilization.gpu,power.draw','--format=csv','-l','1'],stdout=gpu_file)
thread = threading.Thread(target=monitor); thread.start()
remote = '/out/'+out.name
try:
    for group in selected:
        width,height,frames,ratio = groups[group]
        concurrency,count,dataset = 1,a.runs,'coverage'
        # Request frame count is aligned by H3; expected output checked below.
        expected_frames = {240:243,360:362}[frames]  # Verified current 0.28.0 shape planner.
        extra = json.dumps({'model':'/models','num_frames':frames,'fps':24,'guidance_scale':1.0,'true_cfg_scale':1.0,'flow_shift':12.0,'extra_params':json.dumps({'task':'t2va','audio_flow_shift':3.0,'aspect_ratio':ratio})})
        target = out/group; target.mkdir()
        phase.update(group=group,phase='benchmark_including_warmup')
        (target/'profile.json').write_text(json.dumps({'width':width,'height':height,'requested_frames':frames,'expected_output_frames':expected_frames,'fps':24,'requested_seconds':frames/24,'expected_output_seconds':expected_frames/24,'aspect_ratio':ratio,'measured_requests':count,'concurrency':1},indent=2))
        args = ['docker','exec','minimax-h3','python',remote+'/diffusion/diffusion_benchmark_serving.py',
                '--base-url','http://127.0.0.1:8000','--endpoint','/v1/videos','--model','/models',
                '--dataset','custom','--dataset-path',remote+'/'+dataset+'.jsonl','--task','t2v',
                '--num-prompts',str(count),'--max-concurrency',str(concurrency),'--request-rate','inf',
                '--warmup-requests','1','--warmup-num-inference-steps','50','--warmup-concurrency','1',
                '--width',str(width),'--height',str(height),'--num-frames',str(frames),'--fps','24',
                '--seed','1101','--extra-body',extra,'--output-file',remote+'/'+group+'/metrics.json',
                '--save-dir',remote+'/'+group+'/videos']
        (target/'command.json').write_text(json.dumps(args,indent=2))
        print('Starting',group,flush=True)
        with (target/'client.log').open('w') as log:
            command(args,stdout=log,stderr=subprocess.STDOUT)
        metrics=json.loads((target/'metrics.json').read_text())
        print(json.dumps(metrics,indent=2),flush=True)
        phase['phase']='output_validation'
        # Stop if any request failed; preserve all artifacts and server state.
        assert len(list((target/'videos').glob('*.mp4'))) == count, 'Missing output videos; inspect metrics before continuing'
        for video in sorted((target/'videos').glob('*.mp4')):
            path=remote+'/'+group+'/videos/'+video.name
            probe=command(['docker','exec','minimax-h3','ffprobe','-v','error','-show_streams','-of','json',path],capture_output=True,text=True)
            (video.with_suffix('.ffprobe.json')).write_text(probe.stdout)
            streams=json.loads(probe.stdout)['streams']
            v=next(s for s in streams if s['codec_type']=='video')
            au=next(s for s in streams if s['codec_type']=='audio')
            assert (v['width'],v['height'],v.get('nb_frames'),v['r_frame_rate'],v['codec_name']) == (width,height,str(expected_frames),'24/1','h264')
            assert (au['codec_name'],au['sample_rate'],au['channels']) == ('aac','32000',2)
            with video.with_suffix('.decode.log').open('w') as log:
                command(['docker','exec','minimax-h3','ffmpeg','-v','error','-i',path,'-map','0:v:0','-map','0:a:0','-f','null','-'],stdout=log,stderr=subprocess.STDOUT)
finally:
    stop.set(); thread.join(); gpu.terminate(); gpu.wait(); gpu_file.close()
    memory_summary={}
    for group in selected:
        rows=[r for r in memory_samples if r['group']==group and r['phase']=='benchmark_including_warmup']
        if rows:
            memory_summary[group]={'system_used_peak_bytes':max(r['system_used_bytes'] for r in rows),'system_available_min_bytes':min(r['system_available_bytes'] for r in rows),'swap_used_peak_bytes':max(r['swap_used_bytes'] for r in rows),'samples':len(rows),'scope':'whole host, includes existing model/service and warmup; excludes startup; not service-only memory'}
    (out/'memory-summary.json').write_text(json.dumps(memory_summary,indent=2))
    with (out/'server.log').open('w') as log:
        subprocess.run(['docker','logs','minimax-h3'],stdout=log,stderr=subprocess.STDOUT)
    print('Artifacts:',out,flush=True)
