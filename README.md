# Strata + DeepSeek V4.1 Flash 本地优化与鹈鹕测试

这是一次 Windows 本地部署的可复现记录：在 Strata 原版服务之外，使用固定版本的 Xolotl、DSpark 和 DeepSeek Harness，运行 ISTA-DASLab 的 DeepSeek V4.1 Flash 1017 **2.25 bpw / IQ2_XS** 模型。代码、配置、源码补丁、模型元数据和测试结果公开；模型权重及第三方运行时需按指南另行获取。

**This is an independent, experimental Windows reproduction, not an official Strata or DeepSeek release.** The repository contains the selected configuration, custom launchers, two source patches, pinned metadata, and an unedited one-shot Pelican SVG result. We do not distribute model weights or claim identical speed on different hardware.

## 鹈鹕测试

按照 [Simon Willison 的原题](https://simonwillison.net/2024/Oct/25/pelicans-on-a-bicycle/)，向本地模型直接发送一次：

> Generate an SVG of a pelican riding a bicycle

![本机模型一次生成的鹈鹕 SVG 渲染图](benchmark/results/pelican-20261029-run1.png)

2026-10-29 实测：输入 14 token、输出 1,812 token；完整请求 **29.527 秒**，首字 **2.949 秒**，服务报告的生成阶段 **68.2 token/秒**。这是一条短提示的单次结果，不是稳定速度。响应正常结束，提取的 SVG 可解析并成功渲染。图中有鸟形和两个车轮，但脚未踩到踏板、翅膀未触及车把；自行车结构简化。

这是直接调用快速 API 的单轮测试，**不是 Harness 工具调用测试**。没有进行榜单的多评委、多轮评分，不提供官方分数或排名；这个单题展示也不能代表整体能力。[完整测试记录及方法](docs/PELICAN.zh-CN.md) · [原始 JSON](benchmark/results/pelican-20261029-run1.json) · [原样 SVG](benchmark/results/pelican-20261029-run1.svg)

本机此前六题预热结果的加权纯生成速度为 **22.196 token/秒**，按完整请求计算为 **17.659 token/秒**；冷启动六题为 **14.902 / 12.382 token/秒**。不同提示、输出、缓存和负载不可直接比较；未证明所有任务稳定达到 20 token/秒。[原机完整报告](docs/原机运行测试报告.md)

## 选定方案

| 项目 | 记录值 |
| --- | --- |
| 系统与硬件 | Windows 11 x64；Intel Core Ultra 7 265KF；约 95.6 GiB 内存；RTX 5090 D v2（24,455 MiB 显存）；NVMe SSD |
| 模型 | DeepSeek V4.1 Flash 1017，ISTA-DASLab 2.25 bpw / IQ2_XS；模型与共享权重共约 274.78 GB |
| 引擎 | Strata Control / 原版 DeepSeek 引擎 0.1.52；Xolotl `684e3c0693cdb1d928aea525175ef30df9f6ec84` + 本项目补丁 |
| ggml | llama.cpp `6050b467c07a95c7b87debd4ddac2f8ba8d9b807` + 本项目补丁 |
| Harness | `@deepseek-ai/dsh` 0.2.1-rc.2；Node.js 24.14.0；64K 总上下文、16K 单次输出上限 |
| 快速参数 | 48 GiB 专家缓存；PCIe 1.0；路由偏置 0.75 / 0.45；DSpark depth 4、confidence 0.6、Q2_K |
| 接口 | 快速模型 `127.0.0.1:8150`；快速 Harness 网页 `127.0.0.1:3081`；原版回退服务 `127.0.0.1:8080` |

快速模式只支持文本。专家路由偏置会改变输出，可能损失质量；原版图片输入能力仅为服务声明，未在本轮实测。64K 是输入、系统提示和输出共享的总预算，并非 64K 输出。

## 复现和使用

1. 阅读 [公开仓库复现指南](docs/INSTALL.zh-CN.md)，准备 F 盘、对应硬件、固定版依赖和 8 个模型文件。
2. 按指南应用两份补丁、编译 Xolotl，安装本仓库的配置和固定专家排序文件。
3. 启动 `F:\STRATA\start-harness.cmd`；停止使用 `F:\STRATA\stop-harness.cmd`，脚本会尝试恢复原版。
4. 用指南中的健康检查、真实推理、Harness 和停止恢复测试验收。不要与其他用户请求并发运行基准。

`reproduction/overlay` 是公开的**配置和源码快照**，不是完整的离线安装包。没有包含 CUDA、Node、Strata 可执行程序、模型权重、会话或凭据。固定压缩包的上游地址、哈希和源码构建方法见指南。完整离线资料包原先仅保存在测试机，不随本仓库发布。此仓库的完整安装流程**尚未在第二台电脑端到端验证**；原机 Xolotl 二进制按 CUDA `120a` 和本机 CPU 构建，其他硬件可能需要重编译。

## 仓库内容

- `reproduction/overlay/`：选定的启动脚本、两套 Harness 配置、模型 pack 元数据和专家排序文件。
- `reproduction/manifest.json`：快照与八个模型文件的大小和 SHA-256。
- `patches/`：Xolotl DSpark 适配补丁和 llama.cpp/ggml 补丁。
- `tools/`：不覆盖冲突文件的快照安装器和模型内容校验器。
- `benchmark/`：鹈鹕测试脚本、原始响应、SVG、渲染图和历史六题结果。
- `docs/`：公开复现指南、测试说明及原机历史报告。

项目自有代码采用 MIT，第三方来源和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。模型许可与权重取得方式以相应上游模型仓库为准。
