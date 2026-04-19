"""
访问追踪 — 仅供作者本人查看，对普通用户完全透明
─────────────────────────────────────────────
功能：
  1. 每次会话首次访问 → 写入 usage_log.jsonl + 推送飞书
  2. 关键操作（上传文件、点击导出等）→ 写入 + 推送
  3. 隐藏管理员页：URL 加 ?view=__amanda__&token=<TRACKER_TOKEN> 才显示

所有日志：
  - 文件路径：/tmp/airport_obstacle_usage.jsonl（Streamlit Cloud 重启会清空）
  - 飞书 webhook：通过环境变量 TRACKER_FEISHU_WEBHOOK 配置（推荐，永久备份）

环境变量（在 Streamlit Cloud → Secrets 配置）：
  TRACKER_TOKEN          管理员页访问口令（默认 "amanda2026"）
  TRACKER_FEISHU_WEBHOOK 飞书机器人 webhook 完整 URL（可选，配了就推送）
  TRACKER_LOG_PATH       日志路径（默认 /tmp/airport_obstacle_usage.jsonl）
"""
from __future__ import annotations

import json
import os
import time
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib import request as urlrequest, error as urlerror

import streamlit as st


# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
def _cfg(key: str, default: str = "") -> str:
    """优先读 st.secrets，回退到环境变量。"""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


ADMIN_TOKEN = _cfg("TRACKER_TOKEN", "amanda2026")
FEISHU_WEBHOOK = _cfg("TRACKER_FEISHU_WEBHOOK", "")
WECOM_WEBHOOK = _cfg("TRACKER_WECOM_WEBHOOK", "")  # 企业微信群机器人
BARK_URL = _cfg("TRACKER_BARK_URL", "")  # 形如 https://api.day.app/<your_key>

# 日志路径：优先用 ~/.streamlit_data 这种相对持久的路径，回退到 /tmp
def _default_log_path() -> str:
    for cand in [
        os.path.expanduser("~/.streamlit_data/airport_obstacle_usage.jsonl"),
        "/mount/data/airport_obstacle_usage.jsonl",  # streamlit cloud 持久卷（如果挂了）
        "/tmp/airport_obstacle_usage.jsonl",
    ]:
        try:
            Path(cand).parent.mkdir(parents=True, exist_ok=True)
            # 测试可写
            test = Path(cand).parent / ".write_test"
            test.write_text("x")
            test.unlink()
            return cand
        except Exception:
            continue
    return "/tmp/airport_obstacle_usage.jsonl"


LOG_PATH = Path(_cfg("TRACKER_LOG_PATH", _default_log_path()))
CST = timezone(timedelta(hours=8))


# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────
def _now() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _short_id(text: str, length: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def _client_meta() -> dict[str, str]:
    """从 streamlit 的内部 API 拿访客 IP/UA（best-effort，失败返回空）。"""
    info: dict[str, str] = {"ip": "?", "ua": "?", "lang": "?"}
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        from streamlit.runtime import get_instance

        ctx = get_script_run_ctx()
        if ctx is None:
            return info
        runtime = get_instance()
        session_info = runtime._session_mgr.get_session_info(ctx.session_id)
        if session_info is None:
            return info
        client = session_info.client
        # tornado request
        req = getattr(client, "request", None)
        if req is None:
            return info
        # X-Forwarded-For 优先（Streamlit Cloud 走反代）
        headers = req.headers
        ip = (
            headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or headers.get("X-Real-IP", "")
            or req.remote_ip
            or "?"
        )
        info["ip"] = ip
        info["ua"] = headers.get("User-Agent", "?")[:200]
        info["lang"] = headers.get("Accept-Language", "?").split(",")[0]
    except Exception:
        pass
    return info


def _write_log(record: dict[str, Any]) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _post_feishu_async(text: str) -> None:
    """异步推送飞书/企微/Bark，不阻塞页面。"""
    if not (FEISHU_WEBHOOK or WECOM_WEBHOOK or BARK_URL):
        return

    def _send():
        # 飞书
        if FEISHU_WEBHOOK:
            try:
                payload = json.dumps(
                    {"msg_type": "text", "content": {"text": text}},
                    ensure_ascii=False,
                ).encode("utf-8")
                req = urlrequest.Request(
                    FEISHU_WEBHOOK, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                urlrequest.urlopen(req, timeout=4).read()
            except Exception:
                pass
        # 企业微信
        if WECOM_WEBHOOK:
            try:
                payload = json.dumps(
                    {"msgtype": "text", "text": {"content": text}},
                    ensure_ascii=False,
                ).encode("utf-8")
                req = urlrequest.Request(
                    WECOM_WEBHOOK, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                urlrequest.urlopen(req, timeout=4).read()
            except Exception:
                pass
        # Bark (iOS 推送)
        if BARK_URL:
            try:
                from urllib.parse import quote
                title = "障碍物分析访问"
                url = f"{BARK_URL.rstrip('/')}/{quote(title)}/{quote(text[:300])}"
                urlrequest.urlopen(url, timeout=4).read()
            except Exception:
                pass

    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────────
# 对外 API
# ─────────────────────────────────────────────
def track_event(event: str, **details: Any) -> None:
    """记录一个事件（任意名字）。details 是附加字段。"""
    meta = _client_meta()
    sid = st.session_state.get("_tracker_sid")
    if not sid:
        sid = _short_id(f"{meta['ip']}-{meta['ua']}-{time.time()}")
        st.session_state["_tracker_sid"] = sid

    record = {
        "time": _now(),
        "event": event,
        "session": sid,
        "ip": meta["ip"],
        "ip_short": _short_id(meta["ip"], 6),
        "ua": meta["ua"],
        "lang": meta["lang"],
        **details,
    }
    _write_log(record)

    # 飞书消息精简一点
    detail_str = ""
    if details:
        detail_str = " | " + " ".join(f"{k}={v}" for k, v in details.items())
    text = (
        f"🛬 障碍物分析 [{event}]\n"
        f"时间: {record['time']}\n"
        f"会话: {sid}  IP: {meta['ip']}\n"
        f"UA: {meta['ua'][:80]}{detail_str}"
    )
    _post_feishu_async(text)


def track_visit_once() -> None:
    """每个会话只触发一次，记录到访。**必须在 main() 第一行调用。**"""
    if st.session_state.get("_tracker_visited"):
        return
    st.session_state["_tracker_visited"] = True
    track_event("visit")


# ─────────────────────────────────────────────
# 隐藏管理员页
# ─────────────────────────────────────────────
def _read_logs(limit: int = 500) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def maybe_render_admin() -> bool:
    """
    检查 URL 参数 ?view=__amanda__&token=xxx。
    命中 → 渲染管理员页并返回 True（调用方应直接 return，跳过正常 UI）。
    """
    try:
        qp = st.query_params
        view = qp.get("view", "")
        token = qp.get("token", "")
    except Exception:
        return False

    if view != "__amanda__":
        return False

    if token != ADMIN_TOKEN:
        # 无效 token：装作普通用户，什么都不显示
        st.stop()
        return True

    # ── 管理员视图 ──
    st.markdown("## 🔒 访问追踪面板（仅作者可见）")
    pushers = []
    if FEISHU_WEBHOOK: pushers.append("飞书")
    if WECOM_WEBHOOK: pushers.append("企微")
    if BARK_URL: pushers.append("Bark")
    push_status = "、".join(pushers) if pushers else "未配置（只靠本页查看）"
    st.caption(
        f"日志文件：`{LOG_PATH}`　推送通道：{push_status}"
    )

    logs = _read_logs(limit=2000)
    if not logs:
        st.info("📭 暂无访问记录。把网站发给同事让他们打开后再回来看。")
        return True

    # ─── 顶部筛选条 ───
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
    with fc1:
        time_filter = st.selectbox(
            "时间范围",
            ["全部", "最近 1 小时", "最近 24 小时", "最近 7 天", "最近 30 天"],
            index=2,
        )
    with fc2:
        all_events = sorted({r.get("event", "?") for r in logs})
        event_filter = st.multiselect("事件类型", all_events, default=all_events)
    with fc3:
        search = st.text_input("搜索 IP / ICAO / 文件名", "")
    with fc4:
        st.write("")
        st.write("")
        if st.button("🔄 刷新"):
            st.rerun()

    # 过滤
    now = datetime.now(CST)
    cutoffs = {
        "最近 1 小时": now - timedelta(hours=1),
        "最近 24 小时": now - timedelta(hours=24),
        "最近 7 天": now - timedelta(days=7),
        "最近 30 天": now - timedelta(days=30),
    }
    cutoff = cutoffs.get(time_filter)

    filtered = []
    for r in logs:
        if r.get("event") not in event_filter:
            continue
        if cutoff:
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
                if t < cutoff:
                    continue
            except Exception:
                pass
        if search:
            blob = json.dumps(r, ensure_ascii=False).lower()
            if search.lower() not in blob:
                continue
        filtered.append(r)

    # ─── 顶部统计 ───
    total = len(filtered)
    visits = sum(1 for r in filtered if r.get("event") == "visit")
    sessions = len({r.get("session") for r in filtered})
    ips = len({r.get("ip") for r in filtered if r.get("ip") and r.get("ip") != "?"})
    uploads = sum(1 for r in filtered if r.get("event") == "upload")
    exports = sum(1 for r in filtered if r.get("event") == "export")

    st.markdown(f"### 📊 {time_filter}（共 {total} 条事件）")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("👀 访问", visits)
    c2.metric("🧑 独立会话", sessions)
    c3.metric("🌐 独立 IP", ips)
    c4.metric("📤 上传文件", uploads)
    c5.metric("⬇️ 导出报告", exports)

    # ─── IP 排行 ───
    if filtered:
        from collections import Counter
        ip_counter = Counter(
            r.get("ip", "?") for r in filtered if r.get("ip") not in (None, "?")
        )
        if ip_counter:
            with st.expander(f"🏆 访问最多的 IP（共 {len(ip_counter)} 个）", expanded=False):
                for ip, cnt in ip_counter.most_common(15):
                    st.write(f"- `{ip}` — **{cnt}** 次")

    # ─── 完整事件表 ───
    st.markdown("### 📋 详细事件流（最新在上）")
    try:
        import pandas as pd

        df = pd.DataFrame(list(reversed(filtered)))
        cols = [c for c in ["time", "event", "ip", "session", "icao", "file", "fmt", "lang", "ua"] if c in df.columns]
        extra = [c for c in df.columns if c not in cols and c not in ("ip_short", "size_kb", "method", "runways", "obstacles")]
        st.dataframe(
            df[cols + extra],
            use_container_width=True,
            height=600,
            column_config={
                "time": st.column_config.TextColumn("时间", width="medium"),
                "event": st.column_config.TextColumn("事件", width="small"),
                "ip": st.column_config.TextColumn("IP", width="medium"),
                "ua": st.column_config.TextColumn("浏览器", width="large"),
            },
        )
    except Exception as e:
        st.warning(f"表格渲染失败：{e}，改用列表显示")
        for r in list(reversed(filtered))[:200]:
            st.json(r)

    # ─── 下载 ───
    st.markdown("---")
    cdl1, cdl2 = st.columns(2)
    with cdl1:
        raw = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
        st.download_button(
            "⬇️ 下载全部日志 (jsonl)",
            data=raw,
            file_name=f"usage_log_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.jsonl",
            mime="application/jsonl",
            use_container_width=True,
        )
    with cdl2:
        try:
            import pandas as pd
            csv = pd.DataFrame(filtered).to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ 下载当前筛选 (CSV，Excel 可开)",
                data=csv,
                file_name=f"访问日志_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            pass

    st.caption(
        "💡 提示：这一页只有带 token 的 URL 能进，普通访客即使打开 ?view=__amanda__ 也会看到空白页。"
    )
    return True
