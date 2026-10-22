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

## 实验程序与说明

- `ripple_lab/`：网页实验台、Java 节点适配器与网络控制程序。
- `启动Ripple实验台.cmd`：Windows 启动入口。
- `bandwidth_test/`：带宽对照、断联、低速链路测试及结果校验脚本。
- `docs/experiments/`：已整理的测量结果与校验摘要。
- `docs/ripple-slow-link-results-20261022.md`：低速链路三组实验结果。

环境依赖与操作步骤分别见 `ripple_lab/README.md`、`bandwidth_test/README.md` 和 `bandwidth_test/SLOW_LINK_README.md`。本次归档不重新运行长时间弱网实验；已有结果按原报告记录的代码版本和条件解释。
