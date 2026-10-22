"""管理单活实验、历史记录和可复用配置。"""
import copy
import json
from pathlib import Path
import re
import threading
import time
import uuid

from .config import normalize_config
from .event_store import EventStore

TERMINAL = {"completed", "failed", "cancelled"}


class ConflictError(RuntimeError):
    pass


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Manager:
    def __init__(self, root, base_url="http://127.0.0.1:8877", experiment_factory=None):
        self.root = Path(root).resolve()
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        self.factory = experiment_factory
        self.lock = threading.RLock()
        self.instances = {}

    def directory(self, run_id):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", run_id):
            raise KeyError("实验不存在")
        path = self.runs_dir / run_id
        if path.is_symlink() or path.resolve().parent != self.runs_dir:
            raise KeyError("实验路径无效")
        return path

    def get(self, run_id):
        with self.lock:
            if run_id in self.instances:
                return self.instances[run_id].snapshot()
            path = self.directory(run_id) / "state.json"
            if not path.is_file():
                raise KeyError("实验不存在")
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("status") not in TERMINAL:
                state.update(status="failed", stage="failed", error="控制服务曾中断，此实验未正常归档")
            return state

    def runs(self):
        with self.lock:
            identifiers = set(self.instances) | {p.name for p in self.runs_dir.iterdir() if p.is_dir() and not p.is_symlink()}
            values = []
            for identifier in identifiers:
                try:
                    values.append(self.get(identifier))
                except (KeyError, ValueError, OSError):
                    continue
            return sorted(values, key=lambda s: s.get("started_at") or 0, reverse=True)

    def create(self, raw):
        config = normalize_config(raw)
        with self.lock:
            if any(instance.snapshot().get("status") not in TERMINAL for instance in self.instances.values()):
                raise ConflictError("已有实验正在运行，请先结束当前实验")
            if self.factory is None:
                from .experiment import Experiment
                factory = Experiment
            else:
                factory = self.factory
            run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
            instance = factory(self.root, run_id, config, self.base_url)
            self.instances[run_id] = instance
            try:
                instance.start()
            except BaseException:
                self.instances.pop(run_id, None)
                raise
            return instance.snapshot()

    def action(self, run_id, action):
        with self.lock:
            state = self.get(run_id)
            if state.get("status") in TERMINAL:
                return state
            instance = self.instances.get(run_id)
            if instance is None:
                raise ConflictError("历史实验不能继续控制")
            getattr(instance, action)()
            return instance.snapshot()

    def events(self, run_id, **filters):
        self.get(run_id)
        with self.lock:
            instance = self.instances.get(run_id)
            if instance is not None:
                return instance.store.query(**filters)
        path = self.directory(run_id) / "events.sqlite"
        if not path.exists():
            return {"events": [], "total": 0, "next_after": filters.get("after", 0)}
        store = EventStore(path)
        try:
            return store.query(**filters)
        finally:
            store.close()

    def logs(self, run_id, node=""):
        state = self.get(run_id)
        if node and node not in {n["id"] for n in state.get("config", {}).get("nodes", [])}:
            raise ValueError("未知节点")
        folder = self.directory(run_id)
        paths = [folder / "logs" / (node + ".log")] if node else sorted((folder / "logs").glob("*.log")) + [folder / "build.log"]
        chunks = []
        for path in paths:
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 120000))
                    chunks.append("=== " + path.name + " ===\n" + stream.read(120000).decode("utf-8", errors="replace"))
        return {"text": "\n".join(chunks)[-240000:]}

    def configs(self):
        with self.lock:
            path = self.root / "configs.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def save_config(self, body):
        if not isinstance(body, dict):
            raise ValueError("配置必须为对象")
        name = body.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("保存名称需要1～80个字符")
        item = {"name": name.strip(), "config": normalize_config(body.get("config"))}
        with self.lock:
            values = [v for v in self.configs() if v["name"] != item["name"]]
            values.append(item)
            atomic_json(self.root / "configs.json", values)
        return copy.deepcopy(item)

    def close(self):
        with self.lock:
            instances = list(self.instances.values())
            for instance in instances:
                if instance.snapshot().get("status") not in TERMINAL:
                    instance.stop()
        # 先通知所有实验，再在锁外等待清理，防止阻挡状态更新。
        deadline = time.monotonic() + 25
        for instance in instances:
            thread = getattr(instance, "thread", None)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0, deadline - time.monotonic()))
