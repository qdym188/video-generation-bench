"""Download public guide inputs and prepare cases only; never call model APIs."""
import concurrent.futures
import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
GUIDE = 'https://minimaxh3.studio/zh/guide/minimax-h3'
assets = {
 'coffee.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/NKZFbIxuTosdvfxgQTAc7rwrnFh.jpg','5.3'),
 'dunes.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/ICQBbJmYBoCWo0xNCrUcxshonjc.jpg','5.3'),
 'dog-up.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/VRaPb9ETYoQeKKxia03c3moOnae.jpg','2.3'),
 'dog-down.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/DZmTb7d9VoxZ7uxjIUccYxWpn1f.jpg','2.3'),
 'dog-right.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/RpWpb4QN2o2WO3xiFG7coxmdnRc.jpg','2.3'),
 'dog-left.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/EUebblFb1oY6g5x0baUci58nnVP.jpg','2.3'),
 'kitchen-person.jpg': ('image','https://minimaxh3.studio/prompt-library/references/atlas/Km7FbJNLOofRfPxgspZcW5IpnHh.jpg','3.1'),
 'kitchen-motion.mp4': ('video','https://static.atlascloud.ai/model/example/minimax-h3/Zh4Nbsou8oWuiExSLCFcenfzn8g.mp4','3.1'),
 'singer.png': ('image','https://minimaxh3.studio/prompt-library/references/kie/1785486395775_1niKJiZS.png','3.2'),
 'camera-motion.mp4': ('video','https://static.aiquickdraw.com/tools/example/1785486410642_xlRUsi7z.mp4','3.2'),
 'singing.mp3': ('audio','https://static.aiquickdraw.com/tools/example/1785499207880_SwzpjqmX.mp3','3.2'),
 'greenscreen.mp4': ('video','https://static.atlascloud.ai/model/example/minimax-h3/E6V3b0eRTorGUGx3eKUczimKnGa.mp4','5.1'),
 'fairytale.mp4': ('video','https://static.atlascloud.ai/model/example/minimax-h3/LhoEbMXc6oaSq0xOCaxclKE6nXc.mp4','5.1'),
}

def fetch(item):
 name,(kind,url,section)=item
 target=ROOT/'assets'/name
 row={'file':'assets/'+name,'modality':kind,'url':url,'source_page':GUIDE,'section':section,'role':'reference_input_not_example_output'}
 try:
  if not target.exists():
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
   with urllib.request.urlopen(req,timeout=90) as response:
    data=response.read(100*1024**2+1)
   if len(data)>100*1024**2: raise ValueError('Input exceeds 100 MiB preparation limit')
   target.write_bytes(data)
  row.update(status='downloaded',bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
  if kind=='image':
   from PIL import Image
   with Image.open(target) as image:
    image.verify()
   with Image.open(target) as image: row.update(width=image.width,height=image.height,format=image.format)
 except Exception as exc: row.update(status='needs_attention',error=str(exc))
 return row

def case(id,task,section,inputs,prompt,adaptation):
 return {'id':id,'task':task,'source_page':GUIDE,'source_section':section,'inputs':[{'slot':slot,'asset':file,'role':role} for slot,file,role in inputs],
         'prompt':prompt,'prompt_origin':'new test prompt adapted for this test plan; not copied verbatim',
         'adaptation':adaptation,'state':'prepared_not_executed','api_compatibility':'pending current-image input mapping validation',
         'output_matrix':[{'aspect_ratio':r,'width':w,'height':768,'duration_seconds':d,'fps':24,'requested_frames':d*24,'expected_aligned_frames':{10:243,15:362}[d]} for r,w in [('16:9',1344),('4:3',1024)] for d in (10,15)],
         'performance_protocol':{'concurrency':1,'warmup_requests':1,'measured_requests':3,'seed':2101,'num_inference_steps':'omit; use model/client default','cache_note':'current server TeaCache enabled for FL2VA, not Ref2VA; report separately'}}

cases=[
 case('FL-01','fl2va','5.3',[('first_frame','coffee.jpg','starting composition')],
      '以输入图片作为起始画面。镜头缓慢接近杯口，咖啡表面出现轻微涟漪，背景保持安静，伴随轻柔的室内环境声。维持杯子形状和光线方向，整段采用连续镜头。',
      'Single-first-frame test newly designed from guide input; not an original guide FL2VA example.'),
 case('FL-02','fl2va','5.3',[('first_frame','coffee.jpg','starting composition'),('last_frame','dunes.jpg','ending composition')],
      '从第一帧的咖啡画面开始，镜头向咖啡表面推进，颗粒纹理逐渐过渡到沙粒，最终抵达尾帧所示的沙丘构图。保持一个连贯镜头，环境声由室内轻响自然过渡到风声。',
      'Deliberate first/last-frame adaptation; guide original uses two image references, not frame constraints. Confirm last-frame API mapping before execution.'),
 case('REF-01','ref2va','5.3',[('image_1','coffee.jpg','coffee appearance'),('image_2','dunes.jpg','desert appearance')],
      '参考 Image 1 的咖啡材质和 Image 2 的沙丘外观，创作一个从微观颗粒进入广阔沙漠的连续镜头。让纹理变化柔和自然，声音逐渐转为沙漠风声。两图用于外观参考，不要求首尾帧逐像素一致。',
      'Two-image Ref2VA reference case; contrast with FL-02 using identical source files.'),
 case('REF-02','ref2va','2.3',[(f'image_{i}',n,'pose reference') for i,n in enumerate(['dog-up.jpg','dog-down.jpg','dog-right.jpg','dog-left.jpg'],1)],
      '将四张参考图片中的小狗保持为同一角色，在固定视角的手绘场景中依次做拱身、俯低和左右闪避动作。保留纸张质感及角色配色，加入轻快脚步和滑动音效，不加入字幕。',
      'Four-image workload; test pose-reference handling without reproducing the guide UI specification.'),
 case('REF-03','ref2va','3.1',[('image_1','kitchen-person.jpg','character appearance'),('video_1','kitchen-motion.mp4','motion rhythm')],
      '人物外观取自 Image 1，动作节奏参考 Video 1。在厨房场景中呈现轻松的泡沫互动，保留明确的递盘子与躲闪动作，配以自然的水声和笑声。',
      'Image plus video reference.'),
 case('REF-04','ref2va','3.2',[('image_1','singer.png','character appearance'),('audio_1','singing.mp3','vocal reference')],
      '以 Image 1 的人物形象呈现一段演唱，表演和嘴部动作配合 Audio 1 的节奏，保持稳定的中景构图和一致的面部外观。',
      'Image plus audio ablation of guide three-modality case; not audio-only.'),
 case('REF-05','ref2va','3.2',[('image_1','singer.png','character appearance'),('video_1','camera-motion.mp4','camera movement'),('audio_1','singing.mp3','vocal reference')],
      '人物形象依据 Image 1，镜头移动依据 Video 1，演唱节奏与声音依据 Audio 1。让人物表演、镜头变化和声音自然配合，避免切换人物身份。',
      'Image, video and audio combined.'),
 case('REF-06','ref2va','5.1',[('video_1','greenscreen.mp4','foreground motion'),('video_2','fairytale.mp4','background appearance')],
      '保留 Video 1 的前景人物与动作，用 Video 2 的环境风格重新构建背景，使前景边缘、光照和镜头变化协调，生成自然的环境声。',
      'Two-video reference; input duration total must be probed before test execution.'),
]

if __name__=='__main__':
 (ROOT/'assets').mkdir(exist_ok=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: manifest=list(pool.map(fetch,assets.items()))
 (ROOT/'assets-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 (ROOT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'cases':len(cases),'assets':len(manifest),'downloaded':sum(r['status']=='downloaded' for r in manifest),'needs_attention':[r['file'] for r in manifest if r['status']!='downloaded']},ensure_ascii=False))
