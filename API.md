# Backend API 文档

**Base URL**: `http://localhost:<port>`

## 通用响应格式

### 成功响应

各接口根据功能返回相应的 JSON 数据或文件。

### 错误响应

```json
{
  "error": "错误描述信息"
}
```

**常见错误码**:

- `400` - 请求参数错误
- `404` - 资源不存在（任务/文件）
- `409` - 任务状态冲突（如未就绪）
- `500` - 服务器内部错误

---

## 仿真任务管理 API

### 1. 创建仿真任务

```
POST /simulations
```

**请求体** (必填):

```json
{
  "target_distribution": {
    "scenario": "datastream",
    "dataSource": "s1",
    "enableSensorFailure": false,
    "enableNodeFailure": false
  }
}
```

字段说明:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `scenario` | string | 与 `dataSource`、传感器故障后缀共同组成 workload CSV：`{scenario}_{dataSource}_damaged.csv` 或 `_normal.csv`（位于后端 `SOURCE_DATA_DIR`，默认 `datasources/`） |
| `dataSource` | string | 同上 |
| `enableSensorFailure` | boolean | 为 `true` 时使用 `damaged` 后缀，否则 `normal` |
| `enableNodeFailure` | boolean | 写入 HOCON 覆盖：`chaos.enable` |

`scenario` 也可传 `senario`（拼写兼容）。未带请求体或校验失败时返回 `422`。

**HOCON 覆盖**: 在任务 `config.conf` 末尾追加 `chaos.enable` 与 `workload.csv.resourcePath`（CSV 绝对路径）。

**响应** `200`:

```json
{
  "task_id": "sim_datastream-s1-nf0sf0-1234567890_abc123",
  "status": "pending"
}
```

`task_id` 由服务端生成，包含：`sim_`、经清洗截断的 `scenario` 与 `dataSource`（单/多方向、单/多波次等语义由这两个取值的命名约定体现）、`nf0`/`nf1`（节点故障关/开）、`sf0`/`sf1`（传感器故障关/开）、Unix 秒时间戳与 6 位十六进制随机后缀（防冲突）。

---

### 2. 获取任务列表

```
GET /simulations
```

**Query 参数**:

| 参数   | 类型   | 必填 | 默认值 | 说明                                                         |
| ------ | ------ | ---- | ------ | ------------------------------------------------------------ |
| status | string | 否   | -      | 过滤状态:`pending`, `running`, `completed`, `failed` |
| limit  | int    | 否   | 100    | 返回数量限制 (1-500)                                         |
| offset | int    | 否   | 0      | 偏移量                                                       |

**响应** `200`:

```json
{
  "tasks": [
    {
      "task_id": "sim_datastream-s1-nf0sf0-1234567890_abc123",
      "status": "completed",
      "progress": 100.0,
      "pid": null,
      "config_path": "/data/.../config.json",
      "output_dir": "/data/...",
      "error_message": null,
      "created_at": "2025-01-01T00:00:00",
      "start_time": "2025-01-01T00:00:01",
      "end_time": "2025-01-01T00:05:00",
      "real_start_time": 1704067201000
    }
  ]
}
```

---

### 3. 获取任务详情

```
GET /simulations/{task_id}
```

**响应** `200`: 返回 Task 对象 (同上)

---

### 4. 获取任务配置

```
GET /simulations/{task_id}/config
```

**响应** `200`:

```json
{
  "task_id": "sim_datastream-s1-nf0sf0-1234567890_abc123",
  "target_distribution": {
    "scenario": "datastream",
    "dataSource": "s1",
    "enableSensorFailure": false,
    "enableNodeFailure": false,
    "filename": "datastream_s1_normal.csv",
    "resourcePath": "/abs/path/to/datasources/datastream_s1_normal.csv"
  }
}
```

`target_distribution` 为创建任务时持久化的运行参数（含 `filename`、`resourcePath`）。旧任务若无 `launch-params.json` 则返回 `400`。

---

### 5. 获取任务状态

```
GET /simulations/{task_id}/status
```

**响应** `200`: 返回 Task 对象

---

### 6. 下载主要结果文件

```
GET /simulations/{task_id}/result
```

**响应** `200`: 文件下载 (FileResponse)

---

### 7. 列出所有结果文件

```
GET /simulations/{task_id}/files
```

**响应** `200`:

```json
{
  "task_id": "sim_datastream-s1-nf0sf0-1234567890_abc123",
  "files": ["result.json", "events.csv", "report.pdf"]
}
```

---

### 8. 下载指定结果文件

```
GET /simulations/{task_id}/files/{filename}
```

**响应** `200`: 文件下载 (FileResponse)

---

### 9. 删除仿真任务

```
DELETE /simulations/{task_id}
```

**响应** `204`: 无内容

---

### 10. 取消仿真任务

```
POST /simulations/{task_id}/cancel
```

**响应** `204`: 无内容

> 取消运行中或待执行的任务，保留任务记录。

---

## 探测器数据 API

CSV 路径与对应仿真任务在 `launch-params.json` 中记录的 `resourcePath` 一致，**不**再通过环境变量单独指定 detector 数据源。

### 1. 获取探测器数据

```
GET /detector
```

**Query 参数**:

| 参数      | 类型   | 必填 | 说明 |
| --------- | ------ | ---- | ---- |
| `task_id` | string | 是   | `POST /simulations` 返回的任务 ID |
| `sim_time` | int   | 是   | 仿真时间上界（毫秒，含），`>= 0` |

**响应** `200`: `DetectorResponse`（传感器时间序列等）。

**错误**: 任务不存在 `404`；缺少 `launch-params.json` 或 `resourcePath`、CSV 不存在或格式错误时返回 `400`/`404` 及 JSON `{"error":"..."}`。

---

## 仿真回放/可视化 API

### 1. 获取仿真元数据

```
GET /simulations/{task_id}/metadata
```

**响应** `200`:

```json
{
  "sim_time_min": 0,
  "sim_time_max": 3600000,
  "duration_ms": 3600000,
  "host_ids": ["host_0", "host_1"],
  "vm_types": [
    {
      "name": "WebServer",
      "layer": "web",
      "spec_id": 1,
      "cpu_cores": 2,
      "cpu_mips": 1000,
      "memory_mb": 2048,
      "description": "Web服务节点"
    }
  ],
  "layer_order": ["web", "app", "db"],
  "event_counts": {
    "vm_create": 100,
    "vm_destroy": 50
  },
  "parse_errors": 0
}
```

---

### 2. 获取指定时刻的全局快照

```
GET /simulations/{task_id}/snapshot
```

**Query 参数**:

| 参数     | 类型 | 必填 | 说明             |
| -------- | ---- | ---- | ---------------- |
| sim_time | int  | 是   | 仿真时间（毫秒） |

**响应** `200`:

```json
{
  "sim_time": 1000000,
  "hosts": [
    {
      "host_id": "host_0",
      "cpu_usage": 75.5,
      "memory_usage": 60.2,
      "vm_count": 5,
      "vms": [
        {
          "vm_id": "vm_0",
          "vm_type": "WebServer",
          "memory_usage_mb": 512.0,
          "queue_length": 3,
          "running_length": 2
        }
      ]
    }
  ]
}
```

---

### 3. 获取时间线数据

```
GET /simulations/{task_id}/timeline
```

**Query 参数**:

| 参数        | 类型 | 必填 | 默认值 | 说明                  |
| ----------- | ---- | ---- | ------ | --------------------- |
| start_time  | int  | 是   | -      | 开始时间（毫秒）      |
| end_time    | int  | 是   | -      | 结束时间（毫秒）      |
| interval_ms | int  | 否   | 1000   | 采样间隔（100-60000） |

**响应** `200`:

```json
{
  "start": 0,
  "end": 3600000,
  "interval_ms": 1000,
  "points": [
    {
      "sim_time": 0,
      "hosts": [ ... ]
    },
    {
      "sim_time": 1000,
      "hosts": [ ... ]
    }
  ]
}
```

---

### 4. 获取仿真摘要统计

```
GET /simulations/{task_id}/summary
```

**响应** `200`:

```json
{
  "sim_time_min": 0,
  "sim_time_max": 3600000,
  "duration_ms": 3600000,
  "snapshot_count": 3600,
  "host_stats": { "avg": 3.5, "peak": 5.0 },
  "vm_stats": { "avg": 25.0, "peak": 40.0 },
  "cpu_stats": { "avg": 65.0, "peak": 95.0 },
  "memory_stats": { "avg": 50.0, "peak": 80.0 },
  "resource_stats": { "peak": 95.0, "valley": 12.0 },
  "queue_stats": { "peak": 100 },
  "latency_stats": {
    "avg": 150.5,
    "p50": 120.0,
    "p95": 300.0,
    "p99": 500.0,
    "count": 10000
  },
  "event_counts": { ... },
  "parse_errors": 0
}
```

`resource_stats`：对每个 `resource_snapshot` 中每个 host 的 `cpu_usage` 与 `memory_usage`，先算 `max(cpu, memory)` 与 `min(cpu, memory)`；`peak` 为所有前者中的最大值，`valley` 为所有后者中的最小值且忽略不大于 0 的样本（若无可用的正值则 `valley` 为 0）。

---

### 5. 获取 Host 历史数据（ECharts 格式）

```
GET /simulations/{task_id}/hosts/{host_id}/history
```

**Query 参数**:

| 参数       | 类型 | 必填 | 说明             |
| ---------- | ---- | ---- | ---------------- |
| start_time | int  | 是   | 开始时间（毫秒） |
| end_time   | int  | 是   | 结束时间（毫秒） |

**响应** `200`:

```json
{
  "time_range": { "start": 0, "end": 3600000 },
  "series": {
    "cpu_usage": {
      "name": "cpu_usage",
      "data": [[0, 50.0], [1000, 52.5], ...]
    },
    "memory_usage": {
      "name": "memory_usage",
      "data": [[0, 30.0], [1000, 31.2], ...]
    }
  }
}
```

---

### 6. 获取 VM 历史数据（ECharts 格式）

```
GET /simulations/{task_id}/vms/{vm_id}/history
```

**Query 参数**: 同上

**响应** `200`: 结构与 Host 历史数据类似

---

### 7. 获取调用链目标列表

```
GET /simulations/{task_id}/targets
```

响应 `200` :

```json
{
  "targets": [0, 1, 2, ...]
}
```

### 8. 获取调用链数据

```
GET /simulations/{task_id}/call-chain
```

**Query 参数**:

| 参数     | 类型 | 必填 | 说明             |
| -------- | ---- | ---- | ---------------- |
| sim_time | int  | 是   | 仿真时间（毫秒） |

**响应** `200`: 见 `CallChainResponse`（Host/VM 拓扑快照）。

### 9. 获取调用链目标历史

```
GET /simulations/{task_id}/target-hist
```

**Query 参数**:

| 参数      | 类型 | 必填 | 说明             |
| --------- | ---- | ---- | ---------------- |
| sim_time  | int  | 是   | 仿真时间（毫秒） |
| target_id | int  | 是   | 目标 id          |

**响应** `200`:

```json
{
  "sim_time": 1000000,
  "records": [
    {
      "time": 20000,
      "preprocess_mods": ["G0-V2-0-1", "G0-V2-0-2"],
      "recognition_mods": ["G0-V3-0-4", "G0-V3-0-6"],
      "fusion_mods": ["G0-V4-0-7", "G1-V4-0-9"],
      "event": "初始分配"
    },
    {
      "time": 120000,
      "preprocess_mods": ["G0-V2-0-2"],
      "recognition_mods": ["G0-V3-0-6"],
      "fusion_mods": ["G0-V4-0-7", "G1-V4-0-9"],
      "event": "微服务缩容"
    }
  ]
}
```

`event` 由上游 `reason_event` 映射：`INITIAL_ASSIGN` → 初始分配，`SCALE_OUT` → 微服务扩容/负载均衡，`SENSOR_CHANGE` → 传感器变动，`SCALE_IN` → 微服务缩容，`NODE_FAILURE` → 节点损毁，`REQUEST_DONE` → 处理完毕。

---

## WebSocket 实时数据流

### 连接端点

```
WS /simulations/{task_id}/stream
```

**消息格式**:

```json
{
  "type": "snapshot|event|progress|...",
  "data": { ... }
}
```

**使用场景**: 实时推送仿真进度、资源快照、事件等数据到前端可视化界面。

---

## 健康检查

```
GET /health
```

**响应** `200`:

```json
{
  "status": "ok"
}
```

---

## 数据模型

### TaskStatus 枚举

| 值        | 说明   |
| --------- | ------ |
| pending   | 待执行 |
| running   | 执行中 |
| completed | 已完成 |
| failed    | 失败   |

### Task 对象

| 字段            | 类型       | 说明                   |
| --------------- | ---------- | ---------------------- |
| task_id         | string     | 任务唯一标识           |
| status          | TaskStatus | 任务状态               |
| progress        | float      | 进度 (0-100)           |
| pid             | int?       | 进程 ID                |
| config_path     | string?    | 配置文件路径           |
| output_dir      | string?    | 输出目录               |
| error_message   | string?    | 错误信息               |
| created_at      | string     | 创建时间 (ISO 8601)    |
| start_time      | string?    | 开始时间               |
| end_time        | string?    | 结束时间               |
| real_start_time | int?       | 现实开始时间戳（毫秒） |

---

## CORS 配置

后端已启用 CORS，允许跨域请求。具体配置请参考 `app/config.py` 中的 `CORS_ORIGINS` 设置。
