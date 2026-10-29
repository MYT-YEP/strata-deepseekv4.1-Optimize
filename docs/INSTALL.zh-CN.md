# Windows 复现指南

本指南面向全新、空闲的目标机。路径固定为 `F:\STRATA`，不要在已有用户文件或服务上直接覆盖。以下流程按原机版本、配置、补丁和模型文件整理；**尚未在第二台电脑完整执行**。遇到版本、硬件、端口或文件冲突，应保留现状并说明，不能靠更换模型或隐瞒差异来声称复现成功。

## 1. 检查条件

- Windows x64、可用的 F 盘、NVIDIA GPU、可用驱动；原机是 RTX 5090 D v2、约 95.6 GiB RAM。原机配置使用 48 GiB 专家缓存，其他内存还供模型和系统使用；这不是最低硬件要求。
- 模型文件约 274.78 GB（十进制），此外还需控制程序、CUDA 工具链、源码、构建产物、临时目录和余量；建议至少 300 GiB 可用空间。
- 需要 Git、Visual Studio x64 C++ 构建工具、CMake 和 Ninja。原机使用 MSVC 19.50.35728、CMake 4.2、CUDA Toolkit 13.2.51；这些系统构建工具可能位于 F 盘之外。
- 不要占用其他应用正在使用的 8080、8150、3080、3081 端口，也不要中断正在进行的模型请求。

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
Get-PSDrive -Name F | Select-Object Name, Used, Free
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(8080,8150,3080,3081) } | Select-Object LocalAddress,LocalPort,OwningProcess
```

## 2. 固定版本及来源

| 组件 | 来源与 SHA-256 |
| --- | --- |
| Strata Control 0.1.52 | [官方 Windows ZIP](https://github.com/Niko1221/Strata/releases/download/v0.2.7/strata-control-0.1.52-windows-x86_64.zip)，`b8d9352bf283c4f7783d362c11078aa3e40f4c547c6d1591bee87771ceb5eb52`，73,055,714 字节 |
| Strata DeepSeek engine 0.1.52 | [官方 Windows CUDA 13 包](https://github.com/Niko1221/Strata/releases/download/v0.2.7/strata-dsv41-0.1.52-windows-x86_64-cuda-cuda13.tar.gz)，`f1a3ae88f770b0ef2a3adb9fc7a7166af79069532210bf0f9c7970845cb75865`，422,151,870 字节 |
| Node.js 24.14.0 | [官方 Windows x64 ZIP](https://nodejs.org/dist/v24.14.0/node-v24.14.0-win-x64.zip)，`313fa40c0d7b18575821de8cb17483031fe07d95de5994f6f435f3b345f85c66`，36,217,529 字节 |
| Xolotl | `684e3c0693cdb1d928aea525175ef30df9f6ec84`，再应用 `patches/xolotl-local-dspark.patch` |
| llama.cpp / ggml | `6050b467c07a95c7b87debd4ddac2f8ba8d9b807`，再应用 `patches/llama-ggml.patch` |
| CUDA | NVIDIA CUDA 13.2 redist；本机 `nvcc` 为 13.2.51；安装脚本和原机 manifest 快照在 `reproduction/overlay/toolchains/cuda-13.2/` |
| Harness | `@deepseek-ai/dsh` 0.2.1-rc.2；使用本仓库 `package-lock.json` 执行 `npm ci` |

整理时已下载前面三个官方压缩包并核对 SHA-256。Control 包中 5,480 个非缓存文件与原机快照一致；DeepSeek engine 包的 5 个文件也一致。Node 包中 1,835 个原机文件一致，原机另有 npm 自动生成的 `npmrc`，本仓库快照含该文件。这些是源文件比对，**不是另一台电脑已成功启动的证明**。

## 3. 准备本仓库和压缩包

将仓库克隆到例如 `F:\STRATA\open-source\strata-deepseekv4.1-Optimize`，下文 `$repo` 按实际路径修改。先创建 `F:\STRATA\downloads` 和 `F:\STRATA\tmp`。下载上述三个固定压缩包到 `downloads`，分别用 `Get-FileHash -Algorithm SHA256` 与表中值逐个核对；文件已有但不匹配时停止并保留。中断后用支持断点续传的下载器继续，不能使用不同版本的同名文件。

```powershell
$repo = 'F:\STRATA\open-source\strata-deepseekv4.1-Optimize'
$downloads = 'F:\STRATA\downloads'
New-Item -ItemType Directory -Path $downloads,'F:\STRATA\tmp' -Force | Out-Null
Get-FileHash -Algorithm SHA256 (Join-Path $downloads 'strata-control-0.1.52-windows-x86_64.zip')
Get-FileHash -Algorithm SHA256 (Join-Path $downloads 'strata-dsv41-0.1.52-windows-x86_64-cuda-cuda13.tar.gz')
Get-FileHash -Algorithm SHA256 (Join-Path $downloads 'node-v24.14.0-win-x64.zip')
```

确认三个哈希全部匹配后，在下列目标均不存在的前提下解压；如目标已存在或解压中断，先人工检查，不要自动覆盖：

```powershell
$control = 'F:\STRATA\terminal\0.1.52'
$engine = 'F:\STRATA\install\engine-dsv41\0.1.52-windows-x86_64-cuda-cuda13'
$nodeTmp = 'F:\STRATA\toolchains\node-extract-24.14.0'
$node = 'F:\STRATA\toolchains\node-24.14.0'
foreach ($path in @($control,$engine,$nodeTmp,$node,'F:\STRATA\terminal\current')) {
  if (Test-Path -LiteralPath $path) { throw "目标已存在，请先检查：$path" }
}
New-Item -ItemType Directory -Path $control,$engine,$nodeTmp -Force | Out-Null
Expand-Archive -LiteralPath (Join-Path $downloads 'strata-control-0.1.52-windows-x86_64.zip') -DestinationPath $control
& tar.exe -xzf (Join-Path $downloads 'strata-dsv41-0.1.52-windows-x86_64-cuda-cuda13.tar.gz') -C $engine
if ($LASTEXITCODE -ne 0) { throw '原版引擎解压失败，保留目录供检查。' }
Expand-Archive -LiteralPath (Join-Path $downloads 'node-v24.14.0-win-x64.zip') -DestinationPath $nodeTmp
Move-Item -LiteralPath (Join-Path $nodeTmp 'node-v24.14.0-win-x64') -Destination $node
New-Item -ItemType Junction -Path 'F:\STRATA\terminal\current' -Target $control | Out-Null
$python = 'F:\STRATA\terminal\current\python\python.exe'
& $python -B -I -X utf8 -c "import sys,psutil,yaml,regex,numpy; print(sys.version)"
& (Join-Path $node 'node.exe') --version
```

## 4. 安装公开快照、模型和 Harness

先检查冲突，再安装本仓库的 69 个配置、脚本、pack 元数据及排序文件；安装器会校验来源哈希，并拒绝覆盖不同的现有文件。它不下载软件或启动服务。历史快照的 Harness 临时目录为 `F:\STRATA\tmp`。

```powershell
& $python -B -I -X utf8 (Join-Path $repo 'tools\install_overlay.py') --check
if ($LASTEXITCODE -ne 0) { throw '检测到冲突。' }
& $python -B -I -X utf8 (Join-Path $repo 'tools\install_overlay.py')
if ($LASTEXITCODE -ne 0) { throw '配置快照安装失败。' }
```

权重不随本仓库发布。可从原机复制 `data\models\deepseek-v4.1-flash-IST-DAS-2.25bpw` 和 `data\models\deepseek-v4.1-flash-shared` 两个完整目录，也可使用下面的固定 revision 下载器。它将临时文件和来源记录放在模型目录，校验大小及 SHA-256 后才重命名；发现同名的其他下载器 `.part` 时会停止，避免重复下载。中断后使用同一镜像和命令续传。下载器已通过离线小样本的冲突、续传与失败保留测试；**未在第二台电脑完成 275 GB 的网络下载测试**。

```powershell
& $python -B -I -X utf8 (Join-Path $repo 'tools\download_models.py') --dry-run
& $python -B -I -X utf8 (Join-Path $repo 'tools\download_models.py')
if ($LASTEXITCODE -ne 0) { throw '模型下载未完成；保留文件并检查。' }
& $python -B -I -X utf8 (Join-Path $repo 'tools\verify_models.py') --write-markers
if ($LASTEXITCODE -ne 0) { throw '目标模型实际内容校验失败。' }
```

默认使用 `https://hf-mirror.com`，也可显式指定 `--endpoint https://huggingface.co`；切换时不得复用来源不一致的临时文件。`--write-markers` 只在全部八个文件真实哈希正确后补建缺失 `.done`，不会覆盖不同的现有标记。模型哈希来自原机固定版本安装器和已有完成记录；发布时没有重读原机全部 275 GB 权重。

安装 Harness 前，将工作和缓存位置设到 F 盘，然后在包锁定文件所在目录使用 npm：

```powershell
$env:TEMP='F:\STRATA\tmp'; $env:TMP='F:\STRATA\tmp'
$env:APPDATA='F:\STRATA\harness-user\appdata'; $env:LOCALAPPDATA='F:\STRATA\harness-user\localappdata'
$env:USERPROFILE='F:\STRATA\harness-user'; $env:HOMEDRIVE='F:'; $env:HOMEPATH='\STRATA\harness-user'
$env:NPM_CONFIG_CACHE='F:\STRATA\harness-cache\npm'; $env:NPM_CONFIG_USERCONFIG='F:\STRATA\harness-user\.npmrc'
$env:PATH='F:\STRATA\toolchains\node-24.14.0;' + $env:PATH
New-Item -ItemType Directory -Path $env:APPDATA,$env:LOCALAPPDATA,'F:\STRATA\harness-cache\npm','F:\STRATA\harness-workspace' -Force | Out-Null
& 'F:\STRATA\toolchains\node-24.14.0\npm.cmd' ci --prefix 'F:\STRATA\harness' --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Harness 依赖安装失败。' }
```

`npm ci` 安装固定 lockfile 所列依赖；执行依赖的安装脚本前应按自身环境审查。原机源码和配置快照不包含会话或网页认证文件。

## 5. 还原源码并编译快速引擎

先准备本机 CUDA 13.2 工具链。原机脚本 `F:\STRATA\toolchains\cuda-13.2\install-redist.py` 获取 NVIDIA 的 redistributable manifest 并按 manifest 哈希下载和解压到 F 盘；它会刷新本地 manifest，且对已存在的部分解压文件只比较大小。为精确复现，应先核对仓库中的 manifest 和 NVIDIA 发布内容，使用全新的目标目录，并在完成后检查工具链版本。若上游发布内容发生变化或无法获取，停止并报告，不能视为相同工具链。

Git 源码目录必须不存在：

```powershell
git -c core.autocrlf=false clone https://github.com/Indras-Mirror/Xolotl.git 'F:\STRATA\research\Xolotl'
git -C 'F:\STRATA\research\Xolotl' checkout --detach 684e3c0693cdb1d928aea525175ef30df9f6ec84
git -C 'F:\STRATA\research\Xolotl' apply --check (Join-Path $repo 'patches\xolotl-local-dspark.patch')
git -C 'F:\STRATA\research\Xolotl' apply (Join-Path $repo 'patches\xolotl-local-dspark.patch')
git -c core.autocrlf=false clone https://github.com/ggml-org/llama.cpp.git 'F:\STRATA\research\Xolotl\third_party\llama.cpp'
git -C 'F:\STRATA\research\Xolotl\third_party\llama.cpp' checkout --detach 6050b467c07a95c7b87debd4ddac2f8ba8d9b807
git -C 'F:\STRATA\research\Xolotl\third_party\llama.cpp' apply --check (Join-Path $repo 'patches\llama-ggml.patch')
git -C 'F:\STRATA\research\Xolotl\third_party\llama.cpp' apply (Join-Path $repo 'patches\llama-ggml.patch')
```

每个 Git 命令失败都应停止；本机已验证两份补丁能够在指定干净提交应用并还原改动。然后在 **x64 Native Tools Command Prompt** 中，确认 `cl`、`cmake`、`ninja` 可用；以下为与原机相同 CUDA `120a` 的构建示例：

```bat
set "CUDA_PATH=F:\STRATA\toolchains\cuda-13.2\toolkit"
set "TEMP=F:\STRATA\tmp"
set "TMP=F:\STRATA\tmp"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%PATH%"
cmake -S F:\STRATA\research\Xolotl -B F:\STRATA\tuning\20tok-goal\xolotl-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON -DSTRATA_GGML_CUDA=ON -DSTRATA_MMQ_KQUANTS=ON -DCMAKE_CUDA_ARCHITECTURES=120a "-DCMAKE_CUDA_COMPILER=%CUDA_PATH%\bin\nvcc.exe" "-DCUDAToolkit_ROOT=%CUDA_PATH%" "-DSTRATA_GGML_DIR=F:\STRATA\research\Xolotl\third_party\llama.cpp" -DSTRATA_DSV41_FQ_OP=ON -DSTRATA_DSV41_HC_MIX=ON -DSTRATA_BUILD_TESTS=OFF -DSTRATA_BUILD_CONVERSATION_TESTS=OFF "-DCMAKE_CXX_FLAGS=/utf-8" "-DCMAKE_CUDA_FLAGS=-Xcompiler=/utf-8"
cmake --build F:\STRATA\tuning\20tok-goal\xolotl-build --target ds41_generate --parallel 2
```

新 GPU 需根据实际架构及上游支持情况设置 CUDA 架构；不同 CPU、编译器和 GPU 的产物不一定与原机 SHA-256 一样。`strata-profile-xolotl-rank.bin` 必须使用本仓库的原样文件；不要从运行时会变动的 `expert-profile.bin` 重新生成。快速配置在 `tuning\20tok-goal\xolotl-dflash-bias075-full-draft-64k.json`。

## 6. 启动、验收与回退

确认模型、编译产物、原版端口及资源状态后，运行 `F:\STRATA\start-harness.cmd`。启动器会准备原版 64K 模型、在快速版运行时释放原版模型资源，并尝试打开带本机认证信息的 `127.0.0.1:3081` 页面；不要分享认证链接。关闭时运行 `F:\STRATA\stop-harness.cmd`，并确认原版服务恢复。需要原版网页时使用 `start-harness-original.cmd`。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8150/health' | ConvertTo-Json -Depth 8
Invoke-RestMethod 'http://127.0.0.1:8150/v1/models' | ConvertTo-Json -Depth 8
Set-Location 'F:\STRATA\harness-workspace'
& 'F:\STRATA\harness.cmd' --profile headless --json '请用一句话解释模型量化。'
```

健康结果应显示 `loaded=true`、模型 `deepseek-v4.1-flash`、`max_context=65536`；模型列表应显示同一模型已加载。健康检查不等于推理成功：记录实际回答、请求耗时、token、首字和服务提供的生成速度。按 [鹈鹕测试指南](PELICAN.zh-CN.md) 进行同题单轮复测；对重建二进制加入 `--allow-rebuilt-engine` 并记录哈希。也应按原机报告验证 Harness 文件读取、16K 截断边界和停止恢复；没有实测的内容标为未测。

原机的完整离线资料包和其安装程序没有随本 GitHub 仓库发布。[原机离线资料包指南](原机离线资料包指南.md)是历史参考，其中第 5 节的离线包路径只在原机或另行复制过该资料包的电脑上存在，不是本仓库内的路径。
