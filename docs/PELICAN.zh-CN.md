# 鹈鹕 SVG 测试记录

## 方法

- 题目和原始来源：[Simon Willison, Pelicans on a bicycle](https://simonwillison.net/2024/Oct/25/pelicans-on-a-bicycle/)。唯一用户提示词：`Generate an SVG of a pelican riding a bicycle`。
- 2026-10-29 11:37:51 至 11:38:20，香港时间；一轮、一次生成，没有后续提示、人工修改或挑选。
- 本机 Xolotl 快速 API `127.0.0.1:8150/v1/chat/completions`，不经过 Harness UI 或其系统提示。模型 `deepseek-v4.1-flash`，ISTA-DASLab 2.25 bpw / IQ2_XS，64K 上下文，`temperature=0`，`reasoning_effort=none`，`max_tokens=16384`，流式返回。
- 环境：Windows 11 专业版 10.0.26300、Intel Core Ultra 7 265KF、约 95.6 GiB 内存、RTX 5090 D v2 / 24,455 MiB / 驱动 610.88、NVMe SSD。
- 所选运行参数：48 GiB 专家缓存，PCIe 1.0，路由偏置 0.75 / 0.45；配置启用 DSpark，depth 4、confidence 0.6、Q2_K。引擎日志出现 78 个 DFlash 别名映射；但**本次接口的 `draft_n` 和 `draft_n_accepted` 都是 0**，不能据此证明本次请求实际使用草稿加速。
- 健康接口和模型列表均显示模型已加载，开始前原版与快速服务均未报告 busy 或 queued。
- 本次使用的原始脚本保存在 `benchmark/pelican_benchmark_tested.py`，SHA-256 为 `696156fa55c1c38e4c0164199d0837a87fd403ce4286a683457ea143c3f15283`。为方便在新机器复测，`pelican_benchmark.py` 后来增加了允许重编译引擎的选项和引擎哈希记录；本次请求本身未改变。

## 结果

| 指标 | 实测 |
| --- | ---: |
| 输入 / 输出 token | 14 / 1,812 |
| 首字等待 | 2.949 秒 |
| 完整请求 | 29.527 秒 |
| 服务报告的生成阶段 | 26.5843 秒，68.2 token/秒 |
| 结束原因 | `stop` |
| SVG | 4,473 字节；XML 解析和静态渲染成功 |
| SVG SHA-256 | `54325f7f2334fc19cbbb57a4e853c9a59579d389dd566ace4e90bb24013e06a2` |

[原始响应与完整参数](../benchmark/results/pelican-20261029-run1.json) · [从响应提取的原样 SVG](../benchmark/results/pelican-20261029-run1.svg) · [渲染 PNG](../benchmark/results/pelican-20261029-run1.png)。渲染前检查了 XML、脚本、外部图像、事件处理器和外部 URL；这不是对任意 SVG 的全面安全审计。

参照[鹈鹕测试榜的评价维度](https://tihu.app/rules/)，本次只做人工描述：鸟形、橙色喙及两轮可辨；车架是简化三角形，未见清晰链条；双脚没有连接踏板，翅膀没有握住车把。没有调用该榜评委，也没有得到榜单分数。一次样本不足以判断模型稳定性、综合能力或相对排名；服务给出的 68.2 token/秒不能作为其他任务或其他机器的速度承诺。

## 复测

安装并启动选定快速配置、确认模型空闲后：

```powershell
$repo = 'F:\STRATA\open-source\strata-deepseekv4.1-Optimize'
$python = 'F:\STRATA\terminal\current\python\python.exe'
& $python -B -I -X utf8 (Join-Path $repo 'benchmark\pelican_benchmark.py') --output 'F:\STRATA\pelican-run.json'
& $python -B -I -X utf8 (Join-Path $repo 'benchmark\extract_svg.py') 'F:\STRATA\pelican-run.json' 'F:\STRATA\pelican-run.svg'
```

脚本拒绝覆盖结果、检查服务及指定配置，在有其他排队请求时尝试中止以让出资源。默认要求与原机引擎二进制的 SHA-256 一致；若按指南在其他机器重建，使用 `--allow-rebuilt-engine`，并报告实际哈希和硬件差异。请同时记录完整响应、首字、总耗时、token、结束原因和生成参数；未测项目不得填写为成功。
