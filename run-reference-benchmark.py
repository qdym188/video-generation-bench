#!/usr/bin/env python3
"""Functional coverage followed by sequential FL2VA/Ref2VA timing runs."""
import argparse, datetime, hashlib, json, pathlib, statistics, subprocess, threading, time

ROOT=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--execute',action='store_true')
p.add_argument('--cases',default='FL-01,FL-02,REF-01,REF-02,REF-03,REF-04,REF-05,REF-06')
p.add_argument('--runs',type=int,default=3)
p.add_argument('--timeout',type=int,default=7200)
a=p.parse_args()
if not a.execute:
 print('Prepared only. Add --execute for one functional request per case, then 3 measured repetitions per passing case.');raise SystemExit(0)
assert a.runs>0
def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
info=json.loads(run(['docker','inspect','minimax-h3'],capture_output=True,text=True).stdout)[0]
cmd=info['Config']['Cmd']
assert info['State']['Running'] and '--task-type' not in cmd
for key,val in [('--num-gpus','8'),('--tensor-parallel-size','8'),('--dlo-resident-layers','50')]:assert cmd[cmd.index(key)+1]==val
assert 'NCCL_P2P_LEVEL=SYS' in info['Config']['Env']
run(['curl','--fail','--max-time','10','-sS','http://127.0.0.1:8000/health'])
inputs=ROOT/'out'/'reference-cases'
cases=json.loads((inputs/'cases.json').read_text())
ids=a.cases.split(',');cases=[c for c in cases if c['id'] in ids];assert len(cases)==len(ids)
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out=ROOT/'out'/('reference-tp8-r50-'+stamp);out.mkdir()
def save(name,data):(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
save('container.json',info);save('cases.json',cases)
save('protocol.json',{'endpoint':'/v1/videos/sync','shape':[1344,768],'requested_frames':240,'expected_frames':243,'fps':24,'seed':2101,'steps':'omitted; current H3 default','concurrency':1,'functional_per_case':1,'measured_per_case':a.runs,'timing':'curl request upload through full MP4 download; validation outside timing','cache':'FL2VA TeaCache 0.17; Ref2VA uncached','frame_preprocessing':'H3 built-in resize to output canvas; no external image editing'})
manifest=[]
for c in cases:
 for x in c['inputs']:
  asset=inputs/'assets'/x['asset']
  if x['asset']=='greenscreen.mp4':asset=inputs/'derived'/'greenscreen-9.8s.mp4'
  if c['id']=='REF-05' and x['asset']=='camera-motion.mp4':asset=inputs/'derived'/'camera-motion-silent.mp4'
  assert asset.is_file(),asset
  x['local_path']=str(asset)
  manifest.append({'case':c['id'],'slot':x['slot'],'path':str(asset),'bytes':asset.stat().st_size,'sha256':hashlib.file_digest(asset.open('rb'),'sha256').hexdigest()})
save('input-manifest.json',manifest)
stop=threading.Event();phase={'case':None,'phase':'initial','run':None};memory=[]
def monitor():
 with (out/'host-memory.jsonl').open('w') as f:
  while not stop.is_set():
   label=dict(phase)
   m={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in pathlib.Path('/proc/meminfo').read_text().splitlines())}
   stats=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}','minimax-h3'],capture_output=True,text=True,timeout=15)
   row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**label,'system_used_bytes':(m['MemTotal']-m['MemAvailable'])*1024,'system_available_bytes':m['MemAvailable']*1024,'swap_used_bytes':(m['SwapTotal']-m['SwapFree'])*1024,'meminfo_kib':m,'docker_stats':stats.stdout.strip()}
   memory.append(row);f.write(json.dumps(row)+'\n');f.flush();stop.wait(2)
gpu_file=(out/'gpu.csv').open('w')
gpu=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,index,memory.used,utilization.gpu,power.draw','--format=csv','-l','1'],stdout=gpu_file)
thread=threading.Thread(target=monitor,daemon=True);thread.start()
results=[]
def request(c,kind,index):
 phase.update(case=c['id'],phase=kind,run=index)
 folder=out/c['id'];folder.mkdir(exist_ok=True)
 name=f'{kind}-{index}'; video=folder/(name+'.mp4')
 extra={'task':c['task'],'audio_flow_shift':3.0,'aspect_ratio':'16:9'}
 if c['task']=='fl2va':extra['frame_indices']=[0] if len(c['inputs'])==1 else [0,-1]
 fields={'model':'/models','prompt':c['prompt'],'width':'1344','height':'768','num_frames':'240','fps':'24','aspect_ratio':'16:9','seed':'2101','guidance_scale':'1.0','true_cfg_scale':'1.0','flow_shift':'12.0','extra_params':json.dumps(extra)}
 (folder/(name+'-request.json')).write_text(json.dumps({'fields':fields,'inputs':c['inputs']},ensure_ascii=False,indent=2))
 args=['curl','--fail-with-body','--silent','--show-error','--max-time',str(a.timeout),'-D',str(folder/(name+'-headers.txt')),'-w','%{http_code} %{time_total}','-X','POST','http://127.0.0.1:8000/v1/videos/sync']
 for k,v in fields.items():args+=['--form-string',k+'='+v]
 for x in c['inputs']:args+=['-F','input_references=@'+x['local_path']]
 args+=['-o',str(video)]
 print('START',c['id'],kind,index,datetime.datetime.now(datetime.timezone.utc).isoformat(),flush=True)
 start=time.monotonic();response=subprocess.run(args,capture_output=True,text=True)
 row={'case':c['id'],'task':c['task'],'phase':kind,'run':index,'client_wall_seconds':time.monotonic()-start,'curl_exit':response.returncode,'curl_metrics':response.stdout,'error':response.stderr,'success':False}
 if response.returncode==0:
  row['e2e_seconds']=float(response.stdout.split()[-1]);phase['phase']='validation'
  path='/out/'+str(video.relative_to(ROOT/'out'))
  probe=subprocess.run(['docker','exec','minimax-h3','ffprobe','-v','error','-show_streams','-of','json',path],capture_output=True,text=True)
  (folder/(name+'-ffprobe.json')).write_text(probe.stdout or json.dumps({'error':probe.stderr}))
  if probe.returncode==0:
   streams=json.loads(probe.stdout)['streams'];v=next((s for s in streams if s['codec_type']=='video'),{});au=next((s for s in streams if s['codec_type']=='audio'),{})
   row['output_video']={k:v.get(k) for k in ['width','height','nb_frames','r_frame_rate','duration','codec_name']}
   with (folder/(name+'-decode.log')).open('w') as log:dec=subprocess.run(['docker','exec','minimax-h3','ffmpeg','-v','error','-i',path,'-map','0:v:0','-map','0:a:0','-f','null','-'],stdout=log,stderr=subprocess.STDOUT)
   row['decode_exit']=dec.returncode
   row['success']=(v.get('width'),v.get('height'),v.get('nb_frames'),v.get('r_frame_rate'),v.get('codec_name'),au.get('sample_rate'),au.get('channels'))==(1344,768,'243','24/1','h264','32000',2) and dec.returncode==0
  row['bytes']=video.stat().st_size;row['sha256']=hashlib.file_digest(video.open('rb'),'sha256').hexdigest()
 else:
  if video.exists():video.rename(folder/(name+'-error-body.txt'))
 results.append(row);save('results.json',results);print('RESULT',json.dumps(row,ensure_ascii=False),flush=True)
 if response.returncode==28:raise RuntimeError('Client timeout: stop to avoid overlapping an unfinished server request')
 if not row['success']:
  run(['curl','--fail','--max-time','10','-sS','http://127.0.0.1:8000/health'])
 return row['success']

try:
 passing=[]
 for c in cases:
  if request(c,'functional',0):passing.append(c)
 save('functional-summary.json',{'passed':[c['id'] for c in passing],'failed':[c['id'] for c in cases if c not in passing]})
 for c in passing:
  for i in range(1,a.runs+1):
   if not request(c,'measured',i):break
finally:
 stop.set();thread.join(timeout=20);gpu.terminate();gpu.wait();gpu_file.close()
 summary={}
 for c in cases:
  rr=[r for r in results if r['case']==c['id'] and r['phase']=='measured'];ok=[r for r in rr if r['success']]
  mm=[r for r in memory if r['case']==c['id'] and r['phase'] in ('functional','measured')]
  summary[c['id']]={'functional_success':any(r['case']==c['id'] and r['phase']=='functional' and r['success'] for r in results),'measured_n':len(rr),'successful_n':len(ok),'mean_e2e_seconds':statistics.mean(r['e2e_seconds'] for r in ok) if ok else None,'median_e2e_seconds':statistics.median(r['e2e_seconds'] for r in ok) if ok else None,'system_used_peak_bytes':max((r['system_used_bytes'] for r in mm),default=None),'system_available_min_bytes':min((r['system_available_bytes'] for r in mm),default=None)}
 save('summary.json',summary)
 with (out/'server.log').open('w') as log:subprocess.run(['docker','logs','minimax-h3'],stdout=log,stderr=subprocess.STDOUT)
 print('Artifacts:',out,flush=True)
