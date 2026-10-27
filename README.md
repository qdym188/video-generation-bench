# video-generation-bench

面向视频生成服务的性能测试工程，关注**生成时延、吞吐、GPU 显存及主机内存占用**。项目目标是覆盖文生视频、首尾帧条件生成和多模态参考生成，并逐步适配不同模型与服务接口。

**MiniMax-H3 是首个已适配模型**，当前脚本与实测结果基于 vLLM-Omni 0.28.0 单机部署。实现中仍包含 H3 专用参数、容器配置检查及输出校验，尚未实现通用模型适配层，不能直接用于 Wan。其他模型的任务范围、音频能力与帧数约束应在适配后单独声明。

本项目为用户侧测试工程，不是 MiniMax、Wan 或 vLLM 官方基准。

## 目录

- [测试范围](#测试范围)
- [运行环境](#运行环境)
- [快速开始](#快速开始)
- [工具与统计口径](#工具与统计口径)
- [项目结构](#项目结构)
- [结果与状态](#结果与状态)
- [素材来源](#素材来源)

## 测试范围

下列任务与矩阵描述当前 **MiniMax-H3** 适配，不代表所有视频模型的能力。无原生音频输出的模型应另行标记。

| 任务 | 含义 | 当前测试配置 | 默认执行方式 |
| --- | --- | --- | --- |
| T2VA | 文生视音频 | 1344×768 / 1024×768 × 10秒 / 15秒，共4组 | 每组1次预热、5次正式请求，并发1 |
| FL2VA | 首帧／尾帧条件视音频生成 | 1344×768、24 FPS、243帧，约10.125秒 | 每组1次功能预检，通过后3次正式请求，并发1 |
| Ref2VA | 多模态参考视音频生成 | 1344×768、24 FPS、243帧，约10.125秒 | 每组1次功能预检，通过后3次正式请求，并发1 |

T2VA 使用固定 VBench 提示词子集。参考生成包含以下8组用例：

| 用例 | 参考输入 |
| --- | --- |
| FL-01 | 首帧图片 |
| FL-02 | 首帧＋尾帧图片 |
| REF-01 | 双图片 |
| REF-02 | 四图片 |
| REF-03 | 图片＋视频 |
| REF-04 | 图片＋音频 |
| REF-05 | 图片＋视频＋音频 |
| REF-06 | 双视频 |

各用例均配有文字提示词。完整定义见 [cases.json](out/reference-cases/cases.json)；其中的扩展矩阵为候选配置，不代表已全部测试。

## 运行环境

在 Linux 推理服务器上运行，需要 Python 3.11+、Docker 和 curl。

| 配置项 | 当前要求 |
| --- | --- |
| 已验证镜像 | `m.daocloud.io/docker.io/vllm/vllm-omni:v0.28.0` |
| 容器名称 | `minimax-h3` |
| 容器内工具 | `ffmpeg`、`ffprobe` |
| 服务地址 | `http://127.0.0.1:8000` |
| API 模型标识 | `/models` |
| 服务配置检查 | TP8、DLO resident 50、`NCCL_P2P_LEVEL=SYS`，使用组合模型 |
| 目录挂载 | 本仓库 `out` 目录须读写挂载到容器 `/out` |

脚本在推理服务器本地调用 Docker，迁移时须适配容器名与挂载。脚本不会部署、停止或重启服务。

## 快速开始

### 1. 获取项目

```bash
git clone https://github.com/qdym188/video-generation-bench.git
cd video-generation-bench
```

### 2. 准备参考素材

仓库不包含原始素材二进制文件。运行以下命令下载素材：

```bash
python out/reference-cases/prepare_cases.py
```

该程序仅下载素材，不提交生成请求；会重新生成素材清单及用例定义。

确认服务容器及目录挂载满足[运行环境](#运行环境)要求后，准备派生素材：

```bash
bash prepare-derived.sh
```

| 用例 | 处理方式 | 原因 |
| --- | --- | --- |
| REF-05 | 去除 `camera-motion.mp4` 自带音轨，保留画面及独立演唱音频 | 视频自带约6.22秒音轨，与独立音频合计触发15秒上限 |
| REF-06 | 将 `greenscreen.mp4` 裁至约9.83秒 | 使双视频总时长小于15秒 |

所有派生文件另存，原始素材不覆盖；原始失败记录保留。

### 3. 执行测试

不加 `--execute` 只显示说明，不生成视频。以下命令应分别执行，**不要同时启动多个测试脚本**。

T2VA 全部4组配置：

```bash
python run-omni-benchmark.py --execute --group all --runs 5
```

FL2VA 与 Ref2VA 全部用例：

```bash
python run-reference-benchmark.py --execute --runs 3
```

单独补跑 REF-05：

```bash
python run-reference-benchmark.py --execute --cases REF-05 --runs 3
```

参考任务默认单请求超时为7200秒。

## 工具与统计口径

### 测试工具

| 任务 | 工具 | 接口 |
| --- | --- | --- |
| T2VA | 镜像内 `benchmarks/diffusion/diffusion_benchmark_serving.py` | `/v1/videos`，异步提交与轮询 |
| FL2VA / Ref2VA | 自定义 HTTP 测试脚本 | `/v1/videos/sync`，同步请求 |

T2VA 脚本将镜像内工具复制到输出目录，修改轮询超时，并使用标准库 JSONL 加载替换可选 pandas 依赖。修改记录随结果保存；复制逻辑针对0.28.0源码，更新镜像后须重新检查。

### 测量说明

- 参考任务时延包含请求上传至完整 MP4 下载，解码验证不计入请求时延。
- 不显式传入 `num_inference_steps`，沿用已验证版本默认值。
- 输出记录包含请求、结果、ffprobe 元数据、完整解码检查与 SHA-256。
- GPU 显存通过 `nvidia-smi` 约1秒间隔采样；采样峰值不等于瞬时绝对峰值。
- 主机内存按 `MemTotal - MemAvailable` 统计，包括系统其他进程及预检阶段。
- T2VA 与参考任务的接口及计时边界不同，横向比较时应注明。

## 项目结构

```text
video-generation-bench/
├── README.md
├── run-omni-benchmark.py          # T2VA 测试入口
├── run-reference-benchmark.py     # FL2VA / Ref2VA 测试入口
├── prepare-derived.sh            # 派生素材准备
├── benchmark-vbench10.jsonl       # 固定 VBench 提示词子集
├── out/
│   └── reference-cases/
│       ├── cases.json            # 用例定义
│       ├── assets-manifest.json  # 素材来源及校验信息
│       └── prepare_cases.py      # 素材下载与用例准备
└── results/                      # 轻量结果汇总
```

完整结果写入 `out/` 下独立时间戳目录，默认不纳入 Git。生成视频、原始素材、模型权重、镜像、原始服务日志及容器快照不提交。

`benchmark-vbench10.jsonl` 名称沿用原测试工程，正式请求数量由 `--runs` 决定。

## 结果与状态

截至本仓库当前结果快照：

- 2026-10-27原批次：7组参考用例预检成功，并各完成3次正式测试；REF-05 预检失败。
- REF-05 修正补跑已另行启动，结果尚未并入本仓库汇总。
- 已提交的轻量汇总见 [results](results/)。

当前版本保留首个模型的复现实验脚本，后续模型适配可在此基础上扩展。

## 素材来源

参考素材来自 [MiniMax H3 使用指南](https://minimaxh3.studio/zh/guide/minimax-h3)。该网站为独立工作区，不是官方 MiniMax 测试数据集。

来源链接及 SHA-256 见 [assets-manifest.json](out/reference-cases/assets-manifest.json)。素材权利归原权利人，本工程不赋予素材再分发许可，因此默认只提交来源与用例定义。
