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
def _friendly_ua(ua: str) -> str:
    """把浏览器 User-Agent 翻译成『iPhone · Safari』这种大白话。"""
    if not ua or ua == "?":
        return "未知设备"
    s = ua
    sl = s.lower()

    # 设备/系统
    if "iphone" in sl:
        device = "iPhone"
    elif "ipad" in sl:
        device = "iPad"
    elif "android" in sl:
        # 尝试拿型号
        import re
        m = re.search(r"\(linux;[^)]*android[^;]*;\s*([^;)]+)", sl)
        device = "Android · " + m.group(1).strip().title() if m else "Android 手机"
    elif "macintosh" in sl or "mac os x" in sl:
        device = "Mac 电脑"
    elif "windows nt 10" in sl or "windows nt 11" in sl:
        device = "Windows 电脑"
    elif "windows" in sl:
        device = "Windows 电脑"
    elif "linux" in sl:
        device = "Linux 电脑"
    else:
        device = "其他设备"

    # 浏览器（顺序很重要：Edge 含 Chrome、微信含 Safari…）
    if "micromessenger" in sl:
        browser = "微信"
    elif "wxwork" in sl:
        browser = "企业微信"
    elif "lark" in sl or "feishu" in sl:
        browser = "飞书"
    elif "dingtalk" in sl:
        browser = "钉钉"
    elif "qqbrowser" in sl:
        browser = "QQ 浏览器"
    elif "ucbrowser" in sl or "ucweb" in sl:
        browser = "UC 浏览器"
    elif "edg/" in sl or "edge" in sl:
        browser = "Edge"
    elif "opr/" in sl or "opera" in sl:
        browser = "Opera"
    elif "firefox" in sl:
        browser = "Firefox"
    elif "chrome" in sl:
        browser = "Chrome"
    elif "safari" in sl:
        browser = "Safari"
    else:
        browser = "其他浏览器"

    return f"{device} · {browser}"


def _build_visitor_codes(logs: list[dict[str, Any]]) -> dict[str, str]:
    """
    给每个 IP 一个稳定的代号：访客 #01、访客 #02……
    按"第一次出现的时间"排序，所以同一个 IP 永远是同一个号。
    """
    seen: dict[str, str] = {}
    counter = 1
    # 日志已经是按时间顺序写的（追加），所以正向遍历即为首次出现序
    for r in logs:
        ip = r.get("ip", "")
        if not ip or ip == "?":
            continue
        if ip in seen:
            continue
        seen[ip] = f"访客 #{counter:02d}"
        counter += 1
    return seen


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
    st.markdown("## 🔒 访问日志查询（仅王迪可见）")
    st.caption(
        "这个页面是隐藏的，同事使用工具时看不到，他们也不知道存在。"
    )

    logs = _read_logs(limit=2000)
    if not logs:
        st.info("📬 还没有人访问过。把网站地址发给同事让他们打开后，再回来这里看。")
        return True

    # · 访客代号：基于全部历史日志生成（同一 IP 永远同代号）
    visitor_codes = _build_visitor_codes(logs)

    def _ip_label(ip: str) -> str:
        if not ip or ip == "?":
            return "未知"
        code = visitor_codes.get(ip, "访客 #??")
        return f"{code}　({ip})"

    # ─── 顶部筛选条 ───
    # 英文事件名 → 中文
    EVENT_CN = {
        "visit": "👀 访问首页",
        "upload": "📤 上传文件",
        "compute": "⚙️ 运行计算",
        "export": "⬇️ 下载报告",
    }
    def _cn(ev: str) -> str:
        return EVENT_CN.get(ev, ev)

    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
    with fc1:
        time_filter = st.selectbox(
            "看多久以内的记录",
            ["全部", "最近 1 小时", "最近 24 小时", "最近 7 天", "最近 30 天"],
            index=2,
        )
    with fc2:
        all_events = sorted({r.get("event", "?") for r in logs})
        event_labels = [_cn(e) for e in all_events]
        label_to_event = dict(zip(event_labels, all_events))
        picked_labels = st.multiselect("看哪些动作", event_labels, default=event_labels)
        event_filter = [label_to_event[lbl] for lbl in picked_labels]
    with fc3:
        search = st.text_input("按关键字搜（IP、机场代码、文件名）", "")
    with fc4:
        st.write("")
        st.write("")
        if st.button("🔄 重新加载"):
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

    st.markdown(f"### 📊 {time_filter}（共 {total} 条记录）")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("👀 打开首页", visits)
    c2.metric("🧑 访客人次", sessions)
    c3.metric(f"🌐 不同访客", ips, help="同一个 IP 算一个访客，代号不变")
    c4.metric("📤 上传文件", uploads)
    c5.metric("⬇️ 下载报告", exports)

    # ─── 访客名单（代号·IP·次数） ───
    if filtered:
        from collections import Counter
        ip_counter = Counter(
            r.get("ip", "?") for r in filtered if r.get("ip") not in (None, "?")
        )
        if ip_counter:
            st.markdown("### 🧑‍💻 访客名单（同一个代号永远是同一个人/公司）")
            visitor_rows = []
            for ip, cnt in ip_counter.most_common():
                # 查该 IP 最常用的设备 + 最近一次访问
                ua_counter = Counter(
                    _friendly_ua(r.get("ua", "?")) for r in filtered if r.get("ip") == ip
                )
                last_time = max(
                    (r.get("time", "") for r in filtered if r.get("ip") == ip),
                    default="",
                )
                visitor_rows.append({
                    "代号": visitor_codes.get(ip, "访客 #??"),
                    "上网 IP": ip,
                    "最常用设备": ua_counter.most_common(1)[0][0] if ua_counter else "未知",
                    "访问次数": cnt,
                    "最后一次来": last_time,
                })
            try:
                import pandas as pd
                st.dataframe(pd.DataFrame(visitor_rows), use_container_width=True, hide_index=True)
            except Exception:
                for v in visitor_rows:
                    st.write(v)
            st.caption("💡 同一个公司/家庭的多人可能共用一个公网 IP，会被记为同一个代号。")

    # ─── 完整事件表 ───
    st.markdown("### 📋 每一次活动明细（最新的在最上面）")
    try:
        import pandas as pd

        rows = []
        for r in reversed(filtered):
            ip = r.get("ip", "")
            rows.append({
                "时间": r.get("time", ""),
                "访客": visitor_codes.get(ip, "未知") if ip and ip != "?" else "未知",
                "动作": _cn(r.get("event", "?")),
                "机场代码": r.get("icao", ""),
                "文件名": r.get("file", ""),
                "下载格式": r.get("fmt", ""),
                "设备": _friendly_ua(r.get("ua", "")),
                "上网 IP": ip,
                "会话 ID": r.get("session", ""),
            })
        df = pd.DataFrame(rows)
        # 只保留有数据的列
        keep_cols = [c for c in df.columns if df[c].astype(str).str.strip().any()]
        st.dataframe(df[keep_cols], use_container_width=True, height=600)
    except Exception as e:
        st.warning(f"表格显示出错：{e}")
        for r in list(reversed(filtered))[:200]:
            st.json(r)

    # ─── 下载 ───
    st.markdown("---")
    cdl1, cdl2 = st.columns(2)
    with cdl1:
        raw = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
        st.download_button(
            "下载全部原始日志（高级）",
            data=raw,
            file_name=f"原始日志_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.jsonl",
            mime="application/jsonl",
            use_container_width=True,
        )
    with cdl2:
        try:
            import pandas as pd
            csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "下载当前筛选（Excel 可以直接打开）",
                data=csv,
                file_name=f"访问日志_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            pass

    st.divider()
    with st.expander("ℹ️ 各列意思说明（看不懂时点开）", expanded=False):
        st.markdown("""
**怎么看「访客」代号？**
- `访客 #01`、`访客 #02` 是按**第一次来的先后**自动编号的
- **同一个 IP 永远是同一个代号**，所以你看到 `访客 #03` 来过 5 次，就是同一个人/同一个公司
- 如果同事在公司、家里、4G 切换上网，IP 会变 → 会被记成不同代号
- 想给某个代号备注真实姓名？告诉我，我可以加备注功能

**「动作」分别什么意思？**
- 👀 **访问首页** — 有人打开了工具网页（不一定真的用了）
- 📤 **上传文件** — 上传了 PDF / TXT 资料
- ⚙️ **运行计算** — 点了「开始计算」按钮（真正在用）
- ⬇️ **下载报告** — 下载了 Excel 或 TXT 结果（用完导出了）

**「设备」一栏是什么意思？**
- 比如 `iPhone · Safari` = 用 iPhone 自带浏览器打开的
- `Windows 电脑 · Chrome` = 在公司电脑用 Chrome 打开的
- `Mac 电脑 · 微信` = 在 Mac 上的微信里点开链接看
- `Android · 钉钉` = 用安卓手机的钉钉打开的
- 这样你能大致判断：是不是在公司用电脑工作时打开的、是不是手机随便看了下

**「机场代码」**：他在查哪个机场，比如 ZBAA 是北京首都、ZUUU 是成都双流

**「上网 IP」**：纯技术信息，对应「访客代号」用的，一般可以忽略
        """)

    st.caption(
        "🔒 本页面完全隐藏：不在工具菜单里出现，也搜索不到。同事即使猜到 ?view=__amanda__ 也只会看到空白。"
    )
    return True
