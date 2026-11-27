# 带宽优化源码版本归档

`ripple-bandwidth.bundle` 保存原版及优化版的 Git 提交、分支和标签，不包含编译产物。原版源码仍在上一级的 `Ripple/` 中。

## 恢复实验所需的版本标签

在本项目根目录执行以下命令。`Ripple/` 若已有独立 Git 仓库，可跳过第一条命令；请先保存该目录内自己的修改。

```bash
git -C Ripple init
git -C Ripple fetch ../source_versions/ripple-bandwidth.bundle 'refs/heads/master:refs/remotes/archive/master' 'refs/tags/*:refs/tags/*'
git -C Ripple reset --mixed refs/remotes/archive/master
```

最后一条命令设置原版基准的 Git 索引，不覆盖工作区文件。`bandwidth_test/optimization_suite.py` 会按标签导出并构建源码，不切换工作区。

| 标签 | 用途 |
| --- | --- |
| `bandwidth-v0-original` | 原版对照 |
| `bandwidth-v1-compact` | 紧凑编码版本 |
| `bandwidth-v2-adaptive` | 自适应优化版本 |
| `bandwidth-v0-stable` | 带共同稳定性修复的原版实验基准 |
| `bandwidth-v1-stable` | 带共同稳定性修复的紧凑编码实验基准 |
| `bandwidth-v2-stable` | 带共同稳定性修复的自适应优化实验基准 |

也可独立查看完整版本历史：

```bash
git clone source_versions/ripple-bandwidth.bundle Ripple-versions
git -C Ripple-versions log --all --oneline --decorate
```

## 在线查看版本

所有版本标签均已推送到本仓库，可直接在网页上浏览与对比，不必下载 bundle。

| 标签 | 内容 |
| --- | --- |
| `bandwidth-v0-original`、`bandwidth-v0-stable` | 原版基准 / 带连接表并发修复 |
| `bandwidth-v1-compact`、`bandwidth-v1-stable` | UUID 二进制编码 + 同步操作紧凑操作码 |
| `bandwidth-v2-adaptive`、`bandwidth-v2-stable` | 同步与分发载荷自适应 Deflate |

直接对比两个版本：

- v0 → v1（UUID 二进制 + 同步操作紧凑编码，4 个文件）：
  <https://github.com/yuan-jc/oop_class/compare/bandwidth-v0-original...bandwidth-v1-compact>
- v1 → v2（自适应 Deflate，7 个文件）：
  <https://github.com/yuan-jc/oop_class/compare/bandwidth-v1-compact...bandwidth-v2-adaptive>

标签页：<https://github.com/yuan-jc/oop_class/tags>

## 优化版分支

除按标签导出外，优化后的完整源码还以一个普通分支提供，目录结构与 `main` 一致，便于在原有位置查看改动：

- 分支 **`ripple/optimized-v2-stable`**：自 `main` 拉出，把 `Ripple/Ripple/` 整体替换为 `bandwidth-v2-stable` 的内容，diff 仅 12 个文件。
- 对比：<https://github.com/yuan-jc/oop_class/compare/main...ripple/optimized-v2-stable>
- 代码树：<https://github.com/yuan-jc/oop_class/tree/ripple/optimized-v2-stable/Ripple/Ripple>

注意：标签指向的提交把 Ripple 项目放在**仓库根目录**，并且历史根是 Ripple 上游提交（`468e9cb`），与本仓库 `main` 没有共同祖先，因此只适合按标签导出源码或两两对比，不能直接与 `main` 合并。`ripple/optimized-v2-stable` 则是 `main` 的正常后代，可以合并。

bundle 继续保留：它是离线、单文件、不依赖远端的完整备份。

## 实验程序与说明

- `ripple_lab/`：网页实验台、Java 节点适配器与网络控制程序。
- `启动Ripple实验台.cmd`：Windows 启动入口。
- `bandwidth_test/`：带宽对照、断联、低速链路测试及结果校验脚本。
- `docs/experiments/`：已整理的测量结果与校验摘要。
- `docs/ripple-slow-link-results-20261022.md`：低速链路三组实验结果。

环境依赖与操作步骤分别见 `ripple_lab/README.md`、`bandwidth_test/README.md` 和 `bandwidth_test/SLOW_LINK_README.md`。本次归档不重新运行长时间弱网实验；已有结果按原报告记录的代码版本和条件解释。
