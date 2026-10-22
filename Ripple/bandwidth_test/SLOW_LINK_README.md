# 单服务端：1 KiB/s、随机数字消息三组实验

默认一个服务端、一个发布客户端、一个订阅客户端，预先完成订阅。每秒发送一条，持续60秒，共计划60条；正文每条2048字节，前12位是十进制序号，其余为随机数字，测试标识已包含在2048字节中。

这里1 KiB/s＝1024 B/s；不是1 kbit/s。随机数字是UTF-8数字字符串，不是二进制整数数组。三组使用相同种子和相同消息，关闭正文压缩与紧凑编码。

| 组别 | 下行限速 | 额外传播延时 | 随机丢包 |
| --- | --- | --- | --- |
| base | 1024 B/s | 无 | 无 |
| delay | 1024 B/s | 2秒 | 无 |
| loss | 1024 B/s | 无 | 50%网络包 |

只限制服务端→订阅者的下行；反向回复及发布者→服务端不限制。额外2秒延时之外，还会有序列化、排队和重传时间。50%是概率配置，不要求每次恰好丢一半，更不是永久丢一半业务消息。

## 运行

需要 WSL/Linux root、Java/Javac、Maven、ip、tc、ss、tcpdump；建议安装ethtool以关闭分段聚合卸载。

在Windows PowerShell：

```powershell
wsl -u root -- python3 /mnt/d/Ripple/bandwidth_test/slow_link_suite.py --output /var/tmp/ripple-slow-link-run1 --archive-to /mnt/d/Ripple/optimization_results/slow_link
```

Linux：

```bash
sudo python3 bandwidth_test/slow_link_suite.py \
  --output /var/tmp/ripple-slow-link-run1 \
  --size 2048 --rate 1 --duration 60 --bandwidth-bytes 1024 \
  --delay-seconds 2 --loss-percent 50 --max-wait 1800
```

默认从Git标签 `bandwidth-v0-stable` 独立导出构建，原版线格式不变，只包含此前已保存的连接表共同修复。不会切换或修改用户的Ripple工作树。`--source-ref bandwidth-v0-original` 可选择未经修复的原版；`--ripple-root` 可指定已构建发行包目录，两者都记录源码与JAR身份。

输出目录必须是新目录。用 `--cases base`、`--cases delay loss` 选择组别，`--repeats 3` 重复运行。各重复轮次使用不同种子，但同一轮三组种子相同。

## 统计口径

- **60秒时未到达数**：起发后准确60秒，已提交但订阅端原业务处理器尚未完成的消息数，以事件时间回算，不用轮询时刻代替。
- **最后首次到达**：每条消息首次业务接收时间中的最大值，相对起发时刻。
- **停发后收齐时间**：全部收齐时，最后首次到达减60秒；未收齐显示为空，不外推。
- **正确性**：逐条核对发送/接收正文UTF-8字节数、SHA-256；接收端另根据种子与序号重新生成原文并全文比较。重复接收不重复计算消息数。
- **最长等待**：默认停发后最多1800秒，全部到达且PUT响应完成则提前结束；超时仅认定截止未到达。
- **限速实现**：TBF速率8192 bit/s，1600 B令牌桶突发，默认1 MiB队列；额外延时/丢包由TBF下的netem队列实现。掉包发生在该子队列中，不应把配置概率直接换算为实际线上丢失字节占比。
- **单位边界**：2048 B仅是正文，Ripple元数据、TCP/IP、控制消息与重传会增加开销。有限突发和TCP行为使结果不能简单按“每两秒一条”预测。

## 产物

顶层 `README.md`、`results.csv`、`results.json` 是结果汇总。每组目录包含：

- `send-end-checkpoint.json`：停发检查点。
- `slow-link-summary.json`：专用最终统计。
- `per-message-integrity.csv`：每条消息发送、到达时间及两端哈希。
- `publisher-0.jsonl`、`subscriber-1.jsonl`：原始事件与哈希。
- `config.json`、`tc-stats.json`：源码/JAR身份及实际网络配置和计数。
- 原始PCAP、运行日志和数据库副本。

顶层 `*.jsonl` 会被框架按业务事件格式读取。额外诊断应使用 `.json`、`.ndjson` 或单独子目录，避免与业务事件混淆。

`--archive-to` 在结束或失败时将结果复制到指定目录。退出码0表示全部消息提交并正确收齐且没有测量警告；2表示超时未收齐、负载未完整提交或校验问题；其他非零码保留 `failure.txt`。

本脚本不修改Ripple协议，不引入批量合并，不把预备失败组混入正式结果。

全部结束后，可独立重新核验统计与数据库正文：

```bash
python3 bandwidth_test/verify_slow_link.py /var/tmp/ripple-slow-link-run1
```

该命令写出 `unified-verification.json`，逐组重算60秒检查点与最终时间，核对同轮输入相同、源码/JAR一致，并只读检查服务端和订阅端数据库的SQLite完整性、每条正文长度与SHA-256。

原版 `SqliteMaxNumberRecycleStrategy` 会回收同一键的旧版本，因此数据库可能只保留最近几条。全量60条正确性由发送端/接收端事件哈希与接收时全文比较证明；数据库检查只验证仍保留的记录及最新记录，不能把已回收的旧版本算作未送达。

若PCAP存在TCP序号缺口，会单列 `packet_capture_complete=false`，不据此宣称完整的网络字节账本。交付时刻和正文正确性通过独立应用事件核对；应用日志异常、负延时、内容错误或未收齐仍会使交付核验失败。
