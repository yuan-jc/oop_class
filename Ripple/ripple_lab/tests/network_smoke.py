"""需要 root 的真实内核队列验证，普通单元测试不自动执行。"""
import json
from ripple_lab.config import default_config
from ripple_lab.network import Network


def main():
    network = Network(default_config(), "smoke1")
    try:
        network.create()
        link = dict(source="s1", target="c1", bandwidth_kbit=64, delay_ms=20,
                    loss_percent=0, queue_bytes=8192)
        network.shape([link])
        initial = network.stats()["s1"]
        network.fault(link, 10, True)
        fault = network.stats()["s1"]
        network.fault(link, 10, False)
        assert any(q["kind"] == "bfifo" and q["options"]["limit"] == 8192 for q in initial["qdisc"])
        assert any(q["kind"] == "bfifo" for q in fault["qdisc"])
        print(json.dumps(dict(initial=initial, fault=fault), indent=2))
    finally:
        network.cleanup()


if __name__ == "__main__":
    main()
