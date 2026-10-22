# Ripple 可视化实验控制台实施计划

> 执行方式：subagent-driven-development。界面与 Java 适配器分工实现，主代理负责 Python 引擎、集成、测试与审查；持续执行已确认的设计。

**目标：** 双击启动本地实验台，可配置真实逐链路限速、自动构建当前 Ripple、订阅与随机负载、查看各节点记录和原始网页、归档对比。

**架构：** 独立 `ripple_lab/` 应用；Python 标准库控制 HTTP、namespace、tc 和构建，Java 适配器加载真实 Ripple，中文静态网页调用本地 API。新应用目录本身提供隔离，不修改原业务仓库。

**全局约束：** 中文；不改变 Ripple ACK 和重连语义；只用实际源码构建；有向链路独立；固定发送后等待；区分发送、响应、接收和落库；只监听本机；只清理本次资源；记录存磁盘、网页分页；文件按职责拆分至500行以下。

## 接口契约

```json
{
 "name":"基础实验","protocol":"hashing",
 "nodes":[
  {"id":"s1","role":"server","label":"服务端 1"},
  {"id":"p1","role":"publisher","label":"发布者 1","server":"s1","size":1024,"rate":10,"duration":10,"seed":42},
  {"id":"c1","role":"subscriber","label":"订阅者 1","server":"s1"}
 ],
 "links":[{"source":"s1","target":"c1","bandwidth_kbit":512,"delay_ms":0,"loss_percent":0,"queue_bytes":1048576,"fault_start":null,"fault_duration":0}],
 "wait_seconds":10,"baseline_seconds":1,"warmup_timeout":60,"open_node_pages":true
}
```

- 未配置链路即不限速；`bandwidth_kbit=null` 表示不限速。1～8服务端、1～4发布者、1～16订阅者；value32～900000字节，rate0.1～10000，duration0.1～3600，wait0～600。
- 运行配置给节点新增 `ip,namespace,api_port,ui_port,server_number`；顶层新增 `application,run_directory`；发布者键 `load-<id>`，所有订阅者订阅所有发布者键。
- Java：`LabNode <runtime.json> <nodeId>`；classpath包含编译目录、当前构建的server/client.jar和lib。
- Java事件写 `events/<nodeId>.jsonl`，字段 `time,node,event,type,publisher,seq,request_uuid,message_uuid,peer,bytes,ok,preview,note`，Unix秒。
- event：`ready,subscribe,send,write,receive,delivery,wire_send,processed,load_start,load_end,connected,disconnected,error,observation_gap`。`send` 是发布提交，`delivery` 是订阅原处理器返回后的观察，不能视作持久化证明。
- 控制文件位于 `control/`：`stop,start,stop_sending,probe-<publisherId>,ready-<nodeId>,sent-<publisherId>.json`；seq=-1是暖机。sent文件含实际提交数、发送起止时间。
- 状态：`id,name,status,stage,started_at,ended_at,config,version,nodes,summary,warnings,error`；节点：`id,role,label,ip,api_port,ui_port,state,page_url,original_url`。
- summary：`submitted,put_success,received_unique,expected_deliveries,missing,duplicates,latency_ms,per_node,per_publisher,timeseries`。
- `GET /api/defaults` 返回配置；`GET /api/environment`；`GET /api/runs` 返回 `{runs:[]}`；`POST /api/runs` 接收配置返回状态；`GET /api/runs/<id>`；`POST .../stop-sending`；`POST .../stop`。
- `GET .../events?node=&event=&q=&after=0&limit=100` 返回 `{events,total,next_after}`，事件附递增index；`GET .../logs?node=` 返回 `{text}`；`GET .../download` 下载ZIP。
- `GET /api/configs`、`POST /api/configs` 保存 `{name,config}`；网页轮询1秒。节点页 `/?run=<id>&node=<id>`，原网页用独立本地端口HTTP转发。

## 任务1：配置、事件与统计（主代理）

文件：`config.py,event_store.py,tests/test_config.py,tests/test_events.py`。

- [ ] 先写配置非法值、重复有向边、节点引用、消息大小和多发布者标识测试，运行确认失败。
- [ ] 实现 `normalize_config(raw)->dict`、`default_config()->dict`。
- [ ] 实现SQLite事件存储、增量JSONL读取、分页查询、独立响应／送达统计。
- [ ] 验证同序号不同发布者不冲突、重复接收和延迟计算。

## 任务2：Java适配器（工作代理）

文件：`java/LabNode.java`及同目录辅助类。

- [ ] 载荷字节数与可复现性自测先行。
- [ ] 真实Ripple服务端／客户端启动，首连选择，原网页端口，自动订阅全部键。
- [ ] 收发／处理事件、Netty写结果、暖机、定速随机负载、停止、发送计数和观测缺口。
- [ ] 编译自测，不修改业务源码。

## 任务3：中文网页（工作代理）

文件：`web/index.html,app.js,styles.css`，需要时拆模块。

- [ ] 拓扑、节点与有向链路编辑，负载配置、开始／停止与阶段进度。
- [ ] 节点事件、日志、原网页入口、统计、历史对比和配置导入导出。
- [ ] 无CDN；安全渲染；分页和错误状态；自动打开节点页。

## 任务4：构建与真实网络实验（主代理）

文件：`build.py,network.py,experiment.py,tests/test_network.py`。

- [ ] 先测试独立链路命令、清理范围和故障时序，再实现。
- [ ] 源码摘要、Linux隔离构建、Maven缓存和适配器编译，失败不回退旧包。
- [ ] 每节点namespace、实验bridge、按目标IP的HTB/netem/bfifo；管理流量绕开节点间规则。
- [ ] 启动、订阅暖机确认、负载、固定等待、抓包、采样、归档与清理。

## 任务5：HTTP与Windows入口（主代理）

文件：`server.py,launch.ps1,启动实验控制台.cmd,README.md,tests/test_server.py`。

- [ ] HTTP参数、路径和Origin测试先行。
- [ ] 控制API、静态资源、原网页转发与ZIP下载。
- [ ] Windows后台启动WSL、就绪检测和自动浏览器打开。
- [ ] 实测正常、限速积压、短时丢包及多发布者；浏览器操作和数据核对。
- [ ] 最终代码审查，修正重要问题，交付可点击入口与使用说明。

## 验证

单元测试：`python3 -m unittest discover -s ripple_lab/tests -v`。

适配器：当前构建JAR作classpath，`javac -encoding UTF-8 -source 8 -target 8 ...`，运行 `LabNode --self-test`。

端到端：通过HTTP创建短实验，核对网页、summary、tc、原始事件、SQLite和PCAP；取消后清理本次网络并保存记录。
