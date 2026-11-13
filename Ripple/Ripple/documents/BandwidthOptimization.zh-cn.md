# 带宽优化实验版本

此分支保留三种可复查版本：

| 标签 | 版本 | 功能 |
| --- | --- | --- |
| bandwidth-v0-original | V0 | 原版提交468e9cb |
| bandwidth-v1-compact | V1 | UUID由40字节改为16字节，同步操作改为1字节 |
| bandwidth-v2-adaptive | V2 | V1加同步/分发value的自适应Deflate压缩 |

默认开关全部关闭，保留原协议格式。实验集群所有服务端和客户端必须使用相同参数；当前未实现自动协商，不能混用紧凑编码配置，也不能在连接存活期间切换配置。

```text
V0：-Dripple.wire.compact=false -Dripple.wire.compression=false
V1：-Dripple.wire.compact=true  -Dripple.wire.compression=false
V2：-Dripple.wire.compact=true  -Dripple.wire.compression=true
```

V2使用JDK Deflater.BEST_SPEED，原始UTF-8 value达到512字节且完整编码确实变小才使用压缩，否则保留原文字段。压缩只作用于SYNC_REQUEST与DISPATCH_REQUEST的value（包括增量value），未压缩PUT_REQUEST。不会改变副本数、ACK、去重、存储及更新语义。

压缩字段沿用4字节长度位置：非负表示原文字节数；负数表示`-(压缩字节数+1)`，随后为4字节原文长度与raw Deflate内容。接收端拒绝非法、截断、输出长度不符或额外压缩输入，解压长度上限1MiB。外层仍保持原4字节帧长度与原帧上限。

测试：Java8环境执行`mvn -pl ripple-common test`。新增测试覆盖旧格式精确字节、UUID/操作往返、同步/分发/增量、中文、无收益回退、异常长度和解压上限。

外围实验工具位于上一级独立Git仓库的`bandwidth_test/optimization_suite.py`，按照标签导出源码至Linux运行盘构建；每次运行保留源码提交和实际JAR、依赖摘要。Windows挂载盘不用于并发事件读写，避免此前观察到的Errno61文件系统故障。

```bash
cd /mnt/d/Ripple
python3 bandwidth_test/optimization_suite.py --workers 1 --repeats 3 --duration 10 --wait 10 --output /tmp/ripple-wire-reproduce --archive-to /mnt/d/Ripple/optimization_results/reproduce
```

这两个优化不保证任意数据在512/256 kbit/s下都可稳定承载100条/秒。需要结合实际字节、输入速率、P99与截止处理率判断，不以PUT成功替代订阅者处理成功。
