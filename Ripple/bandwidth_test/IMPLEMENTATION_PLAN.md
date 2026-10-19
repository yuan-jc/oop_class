# Ripple 外部带宽测试工具实施计划

目标：在 Ripple 仓库之外实现负载生成、逐消息接收统计、PCAP 分析及隔离链路限速，直接调用已有发行包，保持 Ripple 源码与构建配置不变。

## 架构与边界

- 工具全部位于 `D:\Ripple\bandwidth_test`，源码、编译产物和实验结果均在此目录内。
- Java 驱动外部加载原版客户端 JAR，包装公开的消息处理器注册接口；保留原处理器的存储、响应和后台工作逻辑。
- Python 调度器在专用网络命名空间启动原版服务端 JAR。服务端与发布者共用一个空间，订阅者在另一个空间，专用 veth 承载共享订阅下行。
- 不替换现有网络接口的 qdisc。测试接口使用 tc HTB 限速；退出后删除本次创建的接口和空间。
- 支持 `--size --rate --duration --subscribers --servers --bandwidth --drain-timeout --baseline-duration --output --seed --ripple-root`。
- 输出独立 JSON、CSV、PCAP 和原始事件，报告实际发送、成功响应、唯一投递、截止未送达、延迟分位数和不同流量口径。
- 事件延迟以同一 WSL 系统时钟为基础，在原客户端处理器返回后记录；消息序号包括在指定 value 字节数内。

## 实施步骤

- [x] 1. 先编写统计、消息尺寸、参数校验和 PCAP 拆包/重传的失败测试。
- [x] 2. 实现 `metrics.py`、`capture.py`，运行 `python3 -m unittest discover -s tests -v`。
- [x] 3. 实现独立 `Driver.java`，原处理器执行后输出逐消息事件；用 `javac` 对发行包依赖编译。
- [x] 4. 实现 `runner.py` 和 `run.sh`：预检查、隔离拓扑、进程管理、就绪探测、基线、限速、负载、排空、统计和清理。
- [x] 5. 执行真实不限速单订阅者、多订阅者和低带宽测试，检查 PCAP、tc 统计及接收事件。
- [x] 6. 检查非法参数和 Ctrl+C 清理，确认原 Ripple 仓库无新增改动，补齐中文 README 与中期报告的实施记录。

## 验收命令

```bash
cd /mnt/d/Ripple/bandwidth_test
python3 -m unittest discover -s tests -v
sudo bash run.sh --size 256 --rate 5 --duration 2 --baseline-duration 1
sudo bash run.sh --size 256 --rate 5 --duration 2 --subscribers 2 --baseline-duration 1
sudo bash run.sh --size 4096 --rate 20 --duration 3 --bandwidth 64kbit --drain-timeout 2 --baseline-duration 1
```

低带宽实验不要求所有消息在截止时间前到达；要求限速确实生效，并如实报告延迟、排队与未送达。首次集群启动允许比负载阶段更长的就绪等待。
