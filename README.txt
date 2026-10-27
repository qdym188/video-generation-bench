video-generation-bench
======================

面向视频生成服务的性能测试工程，关注生成时延、吞吐和 GPU／主机内存占用。
项目目标是覆盖文生视频、首尾帧条件生成和多模态参考生成等任务，
并逐步适配不同模型及服务接口。

MiniMax-H3 是首个已适配模型；当前脚本与实测结果基于
vLLM-Omni 0.28.0 的单机部署。当前实现仍包含 H3 专用参数、
容器配置检查及输出校验，尚未实现通用模型适配层，不能直接用于 Wan。
其他模型的任务范围、音频能力与帧数约束应在适配后单独声明。
本项目不是 MiniMax、Wan 或 vLLM 官方基准。

首个适配模型 MiniMax-H3
----------------------
下列任务和测试矩阵均描述当前 H3 适配，不代表所有视频模型的能力。
T2VA 为文生视音频，FL2VA 为首帧／尾帧条件视音频生成，
Ref2VA 为多模态参考视音频生成。无原生音频输出的模型应另行标记。

测试范围
--------
T2VA：4组输出配置，1344x768 / 1024x768 × 10秒 / 15秒。
固定 VBench 提示词；默认每组1次预热、5次正式请求，并发1。
FL2VA：FL-01 首帧；FL-02 首尾帧。
Ref2VA：REF-01 双图；REF-02 四图；REF-03 图片+视频；
REF-04 图片+音频；REF-05 图片+视频+音频；REF-06 双视频。
参考生成目前实测范围为1344x768、24fps、243帧（约10.125秒）。
每组1次功能预检，成功后3次正式请求，并发1。
cases.json 中的扩展矩阵是候选配置，不代表已全部测试。

运行环境与限制
--------------
在 Linux 推理服务器上运行，需要 Python 3.11+、Docker、curl。
运行中的容器名称为 minimax-h3；容器内须包含 ffmpeg/ffprobe。
已验证镜像：m.daocloud.io/docker.io/vllm/vllm-omni:v0.28.0。
脚本校验 TP8、DLO resident 50、NCCL_P2P_LEVEL=SYS，使用组合模型。
服务须监听127.0.0.1:8000，模型标识为/models。
必须将本仓库的 out 目录读写挂载到容器 /out，否则客户端与素材不可见。
这些脚本不是通用远程HTTP客户端；迁移时须适配容器名与挂载。
脚本不会部署、停止或重启服务。

素材准备
--------
本地整理目录已包含原始素材，但 Git 默认忽略这些二进制文件。
新克隆仓库可运行：
  python out/reference-cases/prepare_cases.py
该程序仅下载素材，不提交生成请求，会重新生成素材清单及用例定义。
素材来源：https://minimaxh3.studio/zh/guide/minimax-h3
此网站是独立工作区，不应称为官方 MiniMax 测试数据集。
来源链接及SHA256见assets-manifest.json。素材权利归原权利人，
本工程不赋予素材再分发许可，因此默认只提交来源与用例定义。

在启动参考任务前，运行：
  bash prepare-derived.sh
REF-05：去除camera-motion.mp4自带音轨，只将独立演唱音频用作声音参考。
原素材约6.22秒视频音轨与独立音频合计触发15秒上限；保留失败结果。
REF-06：将greenscreen.mp4裁至约9.83秒，使双视频合计小于15秒。
所有派生文件另存，原始素材不覆盖。

执行命令
--------
不加 --execute 只显示说明，不生成视频。
  python run-omni-benchmark.py --execute --group all --runs 5
  python run-reference-benchmark.py --execute --runs 3
只补跑 REF-05：
  python run-reference-benchmark.py --execute --cases REF-05 --runs 3
不要同时启动多个测试脚本。默认单参考请求超时为7200秒。

工具与统计口径
--------------
T2VA 使用镜像内 benchmarks/diffusion/diffusion_benchmark_serving.py，
向 /v1/videos 提交异步请求。脚本复制该工具至输出目录后修改轮询超时，
并用标准库JSONL加载替换可选pandas依赖；修改记录随结果保存。
该复制逻辑针对0.28.0源码，更新镜像必须重新检查。
FL2VA/Ref2VA 使用自定义HTTP脚本，调用 /v1/videos/sync。
时延包含请求上传至完整MP4下载；解码验证不计入请求时延。
不显式传num_inference_steps，沿用已验证版本默认值。
输出记录包含请求、结果、ffprobe元数据、完整解码检查与SHA256。
GPU显存以nvidia-smi约1秒间隔采样；采样峰值不等于瞬时绝对峰值。
主机内存按MemTotal-MemAvailable统计，包括系统其他进程及预检阶段。
T2VA与参考任务的接口及计时边界不同，横向比较时应注明。

结果与当前状态
--------------
完整结果写入 out/ 下独立时间戳目录，默认不纳入Git。
results/ 保存已完成参考测试的轻量汇总。
2026-10-27原批次：7组预检成功并各完成3次正式测试；REF-05预检失败。
REF-05修正补跑已另行启动，结果尚未并入本目录的汇总。
生成视频、模型权重、镜像、原始服务日志及容器快照不提交。
benchmark-vbench10.jsonl 为本次留存的VBench提示词子集；
名称沿用原测试工程，正式请求数量由 --runs 决定。

仓库：https://github.com/qdym188/video-generation-bench
当前版本保留首个模型的复现实验脚本，后续模型适配可在此基础上扩展。
