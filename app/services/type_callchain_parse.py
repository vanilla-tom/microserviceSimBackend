from __future__ import annotations

from typing import Any, TypedDict

# 解析错误码（可扩展；以下为契约要求的最小集合）
MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
INVALID_ENUM = "INVALID_ENUM"
UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
INVALID_EVENT_TYPE = "INVALID_EVENT_TYPE"

TYPE_ALGORITHM_EVENT = "algorithm_event"
ALGO_NAME_TYPE_CALLCHAIN = "type_callchain"
SUPPORTED_EVENT_VERSION = 2

# reason_event 白名单（与上游契约一致）
REASON_EVENT_WHITELIST = frozenset({
    "INITIAL_ASSIGN",
    "SCALE_OUT",
    "SENSOR_CHANGE",
    "SCALE_IN",
    "NODE_FAILURE",
    "REQUEST_DONE",
})

# reason_event -> 前端历史曲线展示用中文（与旧 API 的 event 字段语义对齐）
REASON_EVENT_TO_DISPLAY_ZH: dict[str, str] = {
    "INITIAL_ASSIGN": "初始分配",
    "SCALE_OUT": "微服务扩容/负载均衡",
    "SENSOR_CHANGE": "传感器变动",
    "SCALE_IN": "微服务缩容",
    "NODE_FAILURE": "节点损毁",
    "REQUEST_DONE": "处理完毕",
}


class TypeCallchainRecord(TypedDict):
    """解析成功后的统一输出结构（camelCase 键，便于直接作为 API 载荷）。"""

    timestampMs: int
    bizType: Any  # 上游 biz_type 可能是 int 或 str，原样透出
    layerVmIds: dict[str, list[str]]
    reasonEvent: str


class TypeCallchainError(TypedDict, total=False):
    """单条失败行的错误描述。"""

    code: str
    t: int
    detail: str


def _as_int_version(raw: Any) -> int | None:
    """将 event_version 规范为 int；无法转换则返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _normalize_layer_vm_ids(raw: Any) -> tuple[dict[str, list[str]] | None, str | None]:
    """校验 layer_vm_ids 为 map<string, string[]>；失败返回 (None, 错误说明)。"""
    if not isinstance(raw, dict):
        return None, "layer_vm_ids 须为 object（map）"
    out: dict[str, list[str]] = {}
    for key, val in raw.items():
        layer_key = key if isinstance(key, str) else str(key)
        if not isinstance(val, list):
            return None, f"layer_vm_ids[{layer_key!r}] 须为字符串数组"
        str_ids: list[str] = []
        for item in val:
            if not isinstance(item, str):
                return None, f"layer_vm_ids[{layer_key!r}] 元素须为字符串"
            str_ids.append(item)
        out[layer_key] = str_ids
    return out, None


def parse_type_callchain_event(ev: dict[str, Any]) -> TypeCallchainRecord | TypeCallchainError:
    """对单条 algorithm_event 行做契约直读。

    调用方应已筛出 algorithm_name == type_callchain；本函数仍校验顶层 type 与版本。
    """
    t = int(ev.get("t", 0))

    if ev.get("type") != TYPE_ALGORITHM_EVENT:
        return {
            "code": INVALID_EVENT_TYPE,
            "t": t,
            "detail": "顶层 type 须为 algorithm_event",
        }

    details = ev.get("details")
    if not isinstance(details, dict):
        return {
            "code": MISSING_REQUIRED_FIELD,
            "t": t,
            "detail": "details 须为 object",
        }

    ver = _as_int_version(details.get("event_version"))
    if ver != SUPPORTED_EVENT_VERSION:
        return {
            "code": UNSUPPORTED_VERSION,
            "t": t,
            "detail": f"仅支持 event_version={SUPPORTED_EVENT_VERSION}，当前为 {details.get('event_version')!r}",
        }

    biz_raw = details.get("biz_type")
    if biz_raw is None or (isinstance(biz_raw, str) and not biz_raw.strip()):
        return {
            "code": MISSING_REQUIRED_FIELD,
            "t": t,
            "detail": "缺少必填字段 biz_type",
        }

    layer_raw = details.get("layer_vm_ids")
    if layer_raw is None:
        return {
            "code": MISSING_REQUIRED_FIELD,
            "t": t,
            "detail": "缺少必填字段 layer_vm_ids",
        }

    layer_map, layer_err = _normalize_layer_vm_ids(layer_raw)
    if layer_map is None:
        return {
            "code": MISSING_REQUIRED_FIELD,
            "t": t,
            "detail": layer_err or "layer_vm_ids 无效",
        }

    reason_raw = details.get("reason_event")
    if reason_raw is None or (isinstance(reason_raw, str) and not str(reason_raw).strip()):
        return {
            "code": MISSING_REQUIRED_FIELD,
            "t": t,
            "detail": "缺少必填字段 reason_event",
        }
    reason_event = str(reason_raw).strip()
    if reason_event not in REASON_EVENT_WHITELIST:
        return {
            "code": INVALID_ENUM,
            "t": t,
            "detail": f"reason_event 不在白名单内: {reason_event!r}",
        }

    return {
        "timestampMs": t,
        "bizType": biz_raw,
        "layerVmIds": layer_map,
        "reasonEvent": reason_event,
    }


def parse_type_callchain_dataset(
    events: list[dict[str, Any]],
    *,
    sim_time: int,
) -> tuple[list[TypeCallchainRecord], list[TypeCallchainError]]:
    """对数据集内所有 type_callchain 候选行解析；仅包含 t<=sim_time 的行。

    同一 events 列表重复解析结果一致；同毫秒事件按其在全量 events 中的下标稳定排序。
    """
    indexed: list[tuple[int, dict[str, Any]]] = []
    for global_idx, ev in enumerate(events):
        if ev.get("algorithm_name") != ALGO_NAME_TYPE_CALLCHAIN:
            continue
        if int(ev.get("t", 0)) > sim_time:
            continue
        indexed.append((global_idx, ev))
    indexed.sort(key=lambda item: (int(item[1].get("t", 0)), item[0]))

    records: list[TypeCallchainRecord] = []
    errors: list[TypeCallchainError] = []

    for _, ev in indexed:
        result = parse_type_callchain_event(ev)
        if "code" in result:
            errors.append(result)  # type: ignore[arg-type]
        else:
            records.append(result)  # type: ignore[arg-type]

    return records, errors


def biz_matches_target(biz: Any, target_id: int) -> bool:
    """判断 biz_type 是否与路径参数 target_id 一致（容忍 int/str）。"""
    if biz is None:
        return False
    try:
        if int(biz) == int(target_id):  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    return str(biz).strip() == str(target_id).strip()


def reason_event_to_display_zh(reason_event: str) -> str:
    """将契约 reason_event 映射为与旧接口一致的 event 中文文案。"""
    return REASON_EVENT_TO_DISPLAY_ZH.get(reason_event, "未知")


def type_callchain_to_target_hist_record(rec: TypeCallchainRecord) -> dict[str, Any]:
    """将 v2 解析结果转为 target-hist API 形状。"""
    layers = rec["layerVmIds"]
    preprocess = layers.get("PREPROCESSOR")
    recog = layers.get("RECOGNIZER")
    fusion = layers.get("ANALYZER")
    return {
        "time": rec["timestampMs"],
        "preprocess_mods": list(preprocess) if isinstance(preprocess, list) else [],
        "recognition_mods": list(recog) if isinstance(recog, list) else [],
        "fusion_mods": list(fusion) if isinstance(fusion, list) else [],
        "event": reason_event_to_display_zh(rec["reasonEvent"]),
    }


def distinct_biz_types(records: list[TypeCallchainRecord]) -> list[int]:
    """从成功解析记录中抽取去重后的 bizType，尽量以 int 返回并排序。"""
    seen: set[int] = set()
    for rec in records:
        b = rec["bizType"]
        try:
            seen.add(int(b))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return sorted(seen)
