# Kubernetes 排查实录：Pod 一直 Pending 的 9 种原因

> 线上出问题时，最贵的不是修复成本，而是定位成本。这份清单是我在三次半夜事故里攒出来的。

Pod 卡在 `Pending` 说明已经被 API Server 接收，但 **没有找到合适的节点** 或者卷没挂上。我们按出现频率从高到低排查。

## 一、最常见的三类

### 1. 资源不足

先看调度器给出的理由：

```bash
kubectl describe pod nginx-7d8b49c5d-2xkwj | tail -n 20
```

输出里重点关注 `Events` 段：

```text
Events:
  Type     Reason            Message
  ----     ------            -------
  Warning  FailedScheduling  0/12 nodes are available: 12 Insufficient cpu.
```

解决思路是二选一：**缩容别的服务** 或者 *扩容节点池*。

| 资源类型 | 检查命令 | 常见坑 |
| :--- | :--- | :--- |
| CPU | `kubectl top node` | request 累加值 > allocatable |
| 内存 | `kubectl top pod -A` | 未设置 limit 导致 OOM |
| GPU | `kubectl get node -o yaml` | 厂商 device-plugin 未注册 |

### 2. 污点没容忍

很多生产集群给节点打了专用污点：

```yaml
spec:
  tolerations:
    - key: "dedicated"
      operator: "Equal"
      value: "gpu"
      effect: "NoSchedule"
```

对应的 Python 巡检脚本（每周自动跑一次）：

```python
import json
from collections import defaultdict

import kubernetes


def find_pending_pods(namespace=None):
    """列出所有 Pending 超过 5 分钟的 Pod。"""
    core = kubernetes.client.CoreV1Api()
    field = "status.phase=Pending"
    resp = core.list_pod_for_all_namespaces(field_selector=field)
    buckets = defaultdict(list)
    for pod in resp.items:
        reason = "unknown"
        for cond in pod.status.conditions or []:
            if cond.reason:
                reason = cond.reason
        buckets[reason].append(f"{pod.metadata.namespace}/{pod.metadata.name}")
    return dict(buckets)


if __name__ == "__main__":
    result = find_pending_pods()
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

### 3. PVC 未绑定

---

## 二、容易被忽略的情况

1. **节点亲和性写错**：`requiredDuringScheduling` 写成了硬性约束
2. **镜像拉取策略**设置成了 `Always` 且私有仓库没配 Secret
3. 打了污点但忘记给 `DaemonSet` 加容忍

最后给一个组合巡检命令，建议写进你的 notes：

```bash
kubectl get pods -A --field-selector=status.phase=Pending \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,AGE:.metadata.creationTimestamp' \
  | sort -k4
```

> 补充一句：如果上面全是 `0/N nodes are available`，大概率不是业务代码的问题，别急着改代码。

参考文档见 [Kubernetes 官方调度器说明](https://kubernetes.io/zh-cn/docs/concepts/scheduling-eviction/kube-scheduler/)。
