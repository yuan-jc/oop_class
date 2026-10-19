# Ripple 发布订阅系统与外部带宽实验

本文件夹归档 Ripple 项目源码、独立带宽测试工具、中期报告及实验抓包，作为 `oop_class` 仓库中的独立项目目录。

## 目录

| 路径 | 内容 |
|---|---|
| [Ripple/](Ripple/) | 原版 Java 发布订阅系统源码、构建配置和许可证 |
| [bandwidth_test/](bandwidth_test/) | 在引擎外部运行的带宽和限速稳定性测试工具 |
| [middle_report/](middle_report/) | 设计、统计口径、预实验和实施验收报告 |
| [traces/](traces/) | 最初的空闲基线、单次发布 PCAP 与逐包记录 |
| [bandwidth_test/results/](bandwidth_test/results/) | 已有实验的统计、原始事件、抓包及日志，包括失败与中断记录 |

## 构建与运行

使用 WSL/Linux、JDK 8 或更高版本及 Maven：

```bash
cd Ripple
mvn install
cd ../bandwidth_test
sudo bash run.sh --size 256 --rate 5 --duration 2 \
  --baseline-duration 1 --drain-timeout 5
```

测试工具还需要 Python 3.12+、iproute2、tcpdump，建议安装 ethtool。网络实验在专用命名空间进行，`sudo` 用于抓包和配置独立测试链路。更多参数及结果解释见 [测试工具说明](bandwidth_test/README.md)。

构建产物、Python 缓存、测试数据库和实验结果中的重复 JAR/编译文件未纳入版本控制，可以通过源码重新生成。已有统计中的绝对路径是原实验环境记录，不要求与克隆后的目录一致。

## 源码来源

`Ripple/` 源码来自 [ISCAS-SSG/Ripple](https://github.com/ISCAS-SSG/Ripple)，归档时版本为 `468e9cb4296110467e3cfdafed412b3dbecfd52a`。原版源码按 [Mulan PSL v2](Ripple/LICENSE) 授权，原作者版权声明和许可证保持原样。

`bandwidth_test/` 为独立测试工具，通过发行包加载原版程序进行实验，不对引擎源码作测试插桩修改。
