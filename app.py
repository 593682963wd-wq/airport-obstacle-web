"""
机场障碍物对飞行影响分析系统 — Web 版
Airport Obstacle Impact Analysis System — Web Edition
基于 ICAO Annex 14 / PANS-OPS 标准
作者: 王迪
"""
import streamlit as st
import tempfile
import os
import io
import math
import traceback
from copy import deepcopy

from core.models import Airport, Runway, QFU, Obstacle, ObstacleResult
from core.pdf_parser import parse_aip_pdf
from core.txt_parser import parse_aip_txt
from core.pep_parser import parse_pep_txt
from core.geometry import compute_obstacle_results, compute_ht_ft, apply_shielding
from core.xlsx_writer import generate_xlsx
from core.txt_writer import write_txt, generate_txt
from templates.constants import M_TO_FT

# ═══════════════════════════════════════════════════════════
# 页面配置
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="✈ 机场障碍物分析系统",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "机场障碍物对飞行影响分析系统 v1.0\n\n作者: 王迪\n\n基于 ICAO Annex 14 / PANS-OPS 标准"
    },
)

# ═══════════════════════════════════════════════════════════
# 自定义主题样式
# ═══════════════════════════════════════════════════════════
st.markdown(
    """
<style>
    /* 全局字体 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    /* 标题区域 */
    .main-header {
        text-align: center;
        padding: 0.5rem 0 0.2rem 0;
    }
    .main-header h1 {
        color: #1565C0;
        font-size: 1.8rem;
        margin-bottom: 0;
    }
    .main-header p {
        color: #78909C;
        font-size: 0.85rem;
        margin-top: 0.2rem;
    }
    /* 信息卡片 */
    .info-box {
        background: #E3F2FD;
        border-left: 4px solid #1565C0;
        padding: 12px 16px;
        border-radius: 4px;
        margin: 8px 0;
        font-size: 0.9rem;
    }
    .warn-box {
        background: #FFF3E0;
        border-left: 4px solid #FF9800;
        padding: 12px 16px;
        border-radius: 4px;
        margin: 8px 0;
        font-size: 0.9rem;
    }
    .ok-box {
        background: #E8F5E9;
        border-left: 4px solid #4CAF50;
        padding: 12px 16px;
        border-radius: 4px;
        margin: 8px 0;
        font-size: 0.9rem;
    }
    /* 步骤指示 */
    .step-num {
        display: inline-block;
        background: #1565C0;
        color: white;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        text-align: center;
        line-height: 28px;
        font-weight: bold;
        margin-right: 8px;
    }
    /* 侧边栏 */
    section[data-testid="stSidebar"] > div {
        padding-top: 1rem;
    }
    /* 下载按钮全宽 */
    .stDownloadButton > button {
        width: 100%;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════════════════════════
def _init():
    for k, v in {
        "airport": None,
        "is_pep": False,
        "computed": False,
        "imp_id": 0,
        "last_fkey": "",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init()

# 资源目录
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


# ═══════════════════════════════════════════════════════════
# 核心逻辑（与 UI 无关）
# ═══════════════════════════════════════════════════════════
def detect_and_parse(uploaded):
    """自动识别文件类型并解析为 Airport 对象."""
    raw = uploaded.getvalue()
    ext = os.path.splitext(uploaded.name)[1].lower()
    suffix = ".pdf" if ext == ".pdf" else ".txt"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        if ext == ".pdf":
            return parse_aip_pdf(tmp_path), False, "AIP PDF"
        text = raw.decode("utf-8", errors="ignore")
        if text.strip().startswith("Version="):
            return parse_pep_txt(tmp_path), True, "PEP TXT"
        return parse_aip_txt(tmp_path), False, "AIP TXT"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def compute_all(airport: Airport):
    """对所有 QFU 执行障碍物分析（复刻桌面版 _compute_obstacles）."""
    ref = airport.reference_runway_idx
    if 0 <= ref < len(airport.runways):
        mrl = airport.runways[ref].max_length
    else:
        mrl = airport.runways[0].max_length if airport.runways else 0

    for ri, rwy in enumerate(airport.runways):
        # 主方向
        for qfu in rwy.main_qfus:
            rs = compute_obstacle_results(
                qfu=qfu, runway=rwy, obstacles=airport.obstacles,
                main_rwy_length=mrl, f6=0,
            )
            rt = compute_obstacle_results(
                qfu=qfu, runway=rwy, obstacles=airport.obstacles,
                main_rwy_length=mrl,
            )
            apply_shielding(rs)
            apply_shielding(rt)

            so = {r.obstacle.seq: r for r in rs if r.is_obstacle}
            to = {r.obstacle.seq: r for r in rt if r.is_obstacle}
            union = set(so) | set(to)

            combined = []
            for r in rs:
                if r.obstacle.seq in union:
                    combined.append(so[r.obstacle.seq] if r.obstacle.seq in so else to[r.obstacle.seq])
                else:
                    combined.append(r)
            qfu.obstacle_results = combined

            n = 0
            for r in combined:
                if r.is_obstacle and not r.is_shielded:
                    n += 1
                    r.comment_label = f"{r.obstacle.seq} A{ri + 1}-{n}"

        # 交叉起飞点复制父方向结果
        for iq in rwy.intersection_qfus:
            parent = next(
                (m for m in rwy.main_qfus
                 if iq.ident.startswith(m.ident + " ") or iq.ident == m.ident),
                None,
            )
            iq.obstacle_results = deepcopy(parent.obstacle_results) if parent and parent.obstacle_results else []


# ═══════════════════════════════════════════════════════════
# 侧边栏
# ═══════════════════════════════════════════════════════════
def sidebar():
    with st.sidebar:
        # ── 数据导入 ──
        st.markdown("### 📂 数据导入")
        st.markdown(
            '<div class="info-box">'
            "<b>支持格式</b><br>"
            "· PEP TXT（推荐）<br>"
            "· AIP PDF<br>"
            "· AIP TXT<br>"
            "<small>系统自动识别，直接上传即可</small>"
            "</div>",
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "上传数据文件",
            type=["txt", "pdf"],
            help="点击或拖拽上传机场障碍物数据文件",
        )

        if uploaded is not None:
            fkey = f"{uploaded.name}|{uploaded.size}"
            if st.session_state.last_fkey != fkey:
                with st.spinner("正在解析文件 …"):
                    try:
                        ap, is_pep, method = detect_and_parse(uploaded)
                        st.session_state.airport = ap
                        st.session_state.is_pep = is_pep
                        st.session_state.computed = False
                        st.session_state.last_fkey = fkey
                        st.session_state.imp_id += 1
                        st.success(f"✅ {method} 导入成功")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 解析失败: {e}")
                        st.code(traceback.format_exc(), language="text")

        # 当前数据状态
        if st.session_state.airport:
            ap = st.session_state.airport
            st.markdown("---")
            st.markdown("### 📋 当前数据")
            st.markdown(
                f"- **机场** {ap.icao} — {ap.name}\n"
                f"- **跑道** {len(ap.runways)} 条\n"
                f"- **障碍物** {len(ap.obstacles)} 个\n"
                f"- **状态** {'✅ 已计算' if st.session_state.computed else '⏳ 待计算'}"
            )

        # ── 资源下载 ──
        st.markdown("---")
        st.markdown("### 📥 资源下载")

        _download_btn("📖 使用说明书 (MD)", "使用说明书.md", "text/markdown")
        _download_btn("📄 使用说明书 (Word)", "使用说明书.docx",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        _download_btn("📊 系统介绍PPT", "机场障碍物分析系统介绍.pptx",
                      "application/vnd.openxmlformats-officedocument.presentationml.presentation")

        # ── 演示视频 ──
        st.markdown("---")
        st.markdown("### 🎬 操作演示")
        vpath = os.path.join(RES, "机场障碍物分析演示.mp4")
        if os.path.exists(vpath):
            st.video(vpath)

        st.markdown("---")
        st.markdown(
            '<p style="text-align:center;color:#aaa;font-size:0.75rem;">'
            "v1.0 · 作者: 王迪 · ICAO Annex 14</p>",
            unsafe_allow_html=True,
        )


def _download_btn(label, fname, mime):
    fpath = os.path.join(RES, fname)
    if os.path.exists(fpath):
        with open(fpath, "rb") as f:
            st.download_button(label, f.read(), file_name=fname, mime=mime,
                               use_container_width=True)


# ═══════════════════════════════════════════════════════════
# 欢迎页
# ═══════════════════════════════════════════════════════════
def welcome():
    st.markdown(
        """
## 👋 欢迎使用

本系统用于分析机场障碍物对飞机起飞离场的影响，遵循 **ICAO Annex 14** 和 **PANS-OPS** 标准。

---

### 🚀 三步完成分析

| | 步骤 | 操作说明 |
|:---:|------|----------|
| <span class="step-num">1</span> | **上传文件** | 在左侧边栏上传 PEP TXT / AIP PDF / AIP TXT 文件 |
| <span class="step-num">2</span> | **设置参数** | 在「✈️ 离场参数」页签中设置转弯角（直飞可跳过） |
| <span class="step-num">3</span> | **计算导出** | 在「💾 导出」页签点击计算，下载 XLSX 和 TXT 文件 |

---

### 📋 支持的文件格式

| 格式 | 说明 | 推荐度 |
|------|------|:------:|
| **PEP TXT** | PEP 系统导出的标准格式文件 | ⭐⭐⭐ |
| **AIP PDF** | 从 AIP 网站下载的 PDF 原始数据 | ⭐⭐ |
| **AIP TXT** | AIP PDF 转存的纯文本文件 | ⭐⭐ |

---

### ✨ 核心功能

- 🔍 **自动解析** — 智能识别 PEP/AIP 格式并提取机场、跑道、障碍物数据
- 📐 **标准计算** — ICAO 1.2% 梯度面 + 保护区包线判定
- 🛡️ **遮蔽检测** — 自动识别被遮蔽的障碍物
- 📊 **Excel 报表** — 含完整公式的 XLSX 分析工作簿
- 📝 **PEP 输出** — 可直接导入 PEP 系统的标准 TXT 文件

---

### 📥 资源下载

左侧边栏提供以下资源，可随时下载：
- 📖 **使用说明书** — 详细的操作指南和计算原理
- 📊 **系统介绍PPT** — 系统功能概览
- 🎬 **操作演示视频** — 完整的操作流程演示

""",
        unsafe_allow_html=True,
    )

    st.info("👈 请在 **左侧边栏** 上传数据文件开始分析")


# ═══════════════════════════════════════════════════════════
# Tab 1: 机场信息
# ═══════════════════════════════════════════════════════════
def tab_airport(ap: Airport):
    st.markdown("### 🏛️ 机场基本信息")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ICAO", ap.icao or "—")
    c2.metric("IATA", ap.iata or "—")
    c3.metric("标高", f"{ap.elevation:.1f} m" if ap.elevation else "—")
    c4.metric("磁差", ap.magnetic_variation or "—")

    st.markdown("---")
    c1, c2 = st.columns(2)
    c1.markdown(f"**名称** {ap.name}")
    c1.markdown(f"**城市** {ap.city}")
    c2.markdown(f"**数据日期** {ap.last_update}")
    c2.markdown(f"**障碍物日期** {ap.obstacle_last_update}")

    st.markdown("---")
    st.markdown("### 📊 数据总览")
    mq = sum(len(r.main_qfus) for r in ap.runways)
    iq = sum(len(r.intersection_qfus) for r in ap.runways)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("跑道", len(ap.runways))
    c2.metric("QFU 方向", f"{mq} + {iq} 交叉")
    c3.metric("障碍物", len(ap.obstacles))
    c4.metric("ILS", "有" if any(r.has_ils for r in ap.runways) else "无")


# ═══════════════════════════════════════════════════════════
# Tab 2: 跑道 / QFU
# ═══════════════════════════════════════════════════════════
def tab_runway(ap: Airport):
    import pandas as pd

    st.markdown("### 🛤️ 跑道 / QFU 数据")
    st.caption("🔵 蓝色 = 交叉起飞点 · 🟢 绿色 = 有 ILS · ⬜ 白色 = 标准方向")

    for ri, rwy in enumerate(ap.runways):
        with st.expander(
            f"跑道 {ri+1} — 磁方位 {rwy.magnetic_heading}° · "
            f"{rwy.max_length}m × {rwy.width}m",
            expanded=True,
        ):
            rows = []
            for q in rwy.qfus:
                kind = (
                    "交叉起飞点" if q.is_intersection
                    else ("ILS" if q.ga_method_flag == 0 else "标准")
                )
                rows.append({
                    "方向": q.ident,
                    "磁方位°": q.magnetic_heading,
                    "TORA": q.tora,
                    "TODA": q.toda,
                    "ASDA": q.asda,
                    "LDA": q.lda,
                    "入口标高m": round(q.threshold_elevation, 1),
                    "坡度%": round(q.slope, 2),
                    "净空道m": q.clearway,
                    "GlideSlope": q.glide_slope if q.glide_slope else "—",
                    "类型": kind,
                })
            df = pd.DataFrame(rows)

            def _color(row):
                if row["类型"] == "交叉起飞点":
                    return ["background-color:#E3F2FD"] * len(row)
                if row["类型"] == "ILS":
                    return ["background-color:#E8F5E9"] * len(row)
                return [""] * len(row)

            st.dataframe(df.style.apply(_color, axis=1),
                         use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════
# Tab 3: 障碍物
# ═══════════════════════════════════════════════════════════
def tab_obstacle(ap: Airport):
    import pandas as pd

    st.markdown("### 🗼 障碍物数据 (AD 2.10)")
    if not ap.obstacles:
        st.warning("暂无障碍物数据")
        return

    rows = []
    for o in ap.obstacles:
        rows.append({
            "序号": o.seq,
            "名称": o.name,
            "磁方位°": o.bearing,
            "距离m": o.distance,
            "坐标": o.coordinate,
            "海拔m": round(o.elevation_m, 1),
            "控制障碍物": o.remark_control,
            "备注": o.note,
        })
    st.dataframe(rows, use_container_width=True, hide_index=True, height=450)
    st.caption(f"共 {len(ap.obstacles)} 个障碍物")


# ═══════════════════════════════════════════════════════════
# Tab 4: 离场参数
# ═══════════════════════════════════════════════════════════
def tab_departure(ap: Airport):
    st.markdown("### ✈️ 离场参数设置")

    st.markdown(
        '<div class="info-box">'
        "<b>操作指南</b><br>"
        "· <b>转弯方向</b>：左转为负角度，右转为正角度，直飞为 0°<br>"
        "· <b>偏移参数</b>：多跑道机场需设置交叉跑道偏移，单跑道保持 0 即可<br>"
        "· 设置完成后请到「💾 导出」页签点击计算"
        "</div>",
        unsafe_allow_html=True,
    )

    # 主跑道选择
    if len(ap.runways) > 1:
        opts = []
        for i, r in enumerate(ap.runways):
            names = "/".join(q.ident for q in r.main_qfus)
            opts.append(f"跑道 {i+1}: {names} ({r.max_length}m)")
        idx = st.selectbox(
            "🎯 主跑道（决定计算时的跑道长度参考）",
            range(len(opts)),
            format_func=lambda x: opts[x],
            index=min(ap.reference_runway_idx, len(opts) - 1),
            key=f"ref_{st.session_state.imp_id}",
        )
        ap.reference_runway_idx = idx

    st.markdown("---")
    iid = st.session_state.imp_id

    for ri, rwy in enumerate(ap.runways):
        st.markdown(f"#### 跑道 {ri + 1}")
        for qfu in rwy.main_qfus:
            with st.expander(f"QFU {qfu.ident}（磁方位 {qfu.magnetic_heading}°）", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**🔄 离场转弯**")
                    if qfu.departure_turn_angle < 0:
                        di = 1
                    elif qfu.departure_turn_angle > 0:
                        di = 2
                    else:
                        di = 0

                    direction = st.selectbox(
                        "转弯方向",
                        ["直飞 (0°)", "左转 (负角度)", "右转 (正角度)"],
                        index=di,
                        key=f"d_{qfu.ident}_{iid}",
                    )
                    if direction.startswith("直飞"):
                        qfu.departure_turn_angle = 0.0
                    else:
                        ang = st.number_input(
                            "角度 (°)",
                            min_value=0.0, max_value=90.0,
                            value=abs(qfu.departure_turn_angle),
                            step=1.0,
                            key=f"a_{qfu.ident}_{iid}",
                        )
                        qfu.departure_turn_angle = -ang if direction.startswith("左转") else ang

                with c2:
                    st.markdown("**📐 坐标偏移**（多跑道时需要）")
                    qfu.departure_x_offset = st.number_input(
                        "E4: 交叉跑道 x 轴位移 (m)", value=qfu.departure_x_offset,
                        step=1.0, key=f"e4_{qfu.ident}_{iid}")
                    qfu.rotation_angle = st.number_input(
                        "F4: x 轴旋转角度 (°)", value=qfu.rotation_angle,
                        step=0.1, key=f"f4_{qfu.ident}_{iid}")
                    qfu.arp_offset = st.number_input(
                        "G4: 基准点 x 轴位移 (m)", value=qfu.arp_offset,
                        step=1.0, key=f"g4_{qfu.ident}_{iid}")
                    qfu.lateral_offset = st.number_input(
                        "E6: 跑道中心 y 轴位移 (m)", value=qfu.lateral_offset,
                        step=1.0, key=f"e6_{qfu.ident}_{iid}")


# ═══════════════════════════════════════════════════════════
# Tab 5: 分析结果
# ═══════════════════════════════════════════════════════════
def tab_results(ap: Airport):
    import pandas as pd

    st.markdown("### 📊 分析结果")

    if not st.session_state.computed:
        st.info("⏳ 请先在「💾 导出」页签点击 **计算分析** 按钮")
        return

    for rwy in ap.runways:
        for qfu in rwy.qfus:
            if not qfu.obstacle_results:
                continue
            lbl = f"QFU {qfu.ident}"
            if qfu.is_intersection:
                lbl += "（交叉起飞点）"

            with st.expander(lbl, expanded=True):
                rows = []
                for r in qfu.obstacle_results:
                    if r.is_obstacle and not r.is_shielded:
                        tag = "🔴 有效障碍物"
                    elif r.is_obstacle and r.is_shielded:
                        tag = "⚪ 被遮蔽"
                    else:
                        tag = "🔵 非障碍物"
                    rows.append({
                        "序号": r.obstacle.seq,
                        "名称": r.obstacle.name,
                        "判定": tag,
                        "DIST(m)": r.dist_from_end,
                        "HT(m)": round(r.ht_above_end, 1),
                        "HT(ft)": compute_ht_ft(r.ht_above_end) if r.ht_above_end else 0,
                        "标注": r.comment_label,
                    })

                df = pd.DataFrame(rows)

                def _c(row):
                    if "有效" in str(row["判定"]):
                        return ["background-color:#FFCDD2"] * len(row)
                    if "遮蔽" in str(row["判定"]):
                        return ["background-color:#E0E0E0"] * len(row)
                    return ["background-color:#E3F2FD"] * len(row)

                st.dataframe(df.style.apply(_c, axis=1),
                             use_container_width=True, hide_index=True)

                eff = sum(1 for r in qfu.obstacle_results if r.is_obstacle and not r.is_shielded)
                shd = sum(1 for r in qfu.obstacle_results if r.is_obstacle and r.is_shielded)
                tot = len(qfu.obstacle_results)
                st.caption(
                    f"共 {tot} 个 · 🔴 有效 {eff} · ⚪ 遮蔽 {shd} · 🔵 非障碍物 {tot-eff-shd}"
                )


# ═══════════════════════════════════════════════════════════
# Tab 6: 导出
# ═══════════════════════════════════════════════════════════
def tab_export(ap: Airport):
    st.markdown("### 💾 计算与导出")

    # ── 第一步 ──
    st.markdown(
        '<div class="step-num">1</div> <b>计算分析</b>',
        unsafe_allow_html=True,
    )

    if st.session_state.is_pep:
        st.markdown(
            '<div class="info-box">PEP 模式：已含障碍物数据，可直接导出。'
            "点击「计算」确认结果。</div>",
            unsafe_allow_html=True,
        )

    c1, c2 = st.columns([1, 3])
    with c1:
        btn = st.button(
            "🔄 计算分析" if not st.session_state.computed else "🔄 重新计算",
            type="primary",
            use_container_width=True,
        )
    if btn:
        with st.spinner("正在计算 …"):
            try:
                if not st.session_state.is_pep:
                    compute_all(ap)
                st.session_state.computed = True
                st.success("✅ 计算完成！请下载结果文件")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 计算失败: {e}")
                st.code(traceback.format_exc())

    if not st.session_state.computed:
        st.markdown(
            '<div class="warn-box">⏳ 请先点击上方「计算分析」按钮</div>',
            unsafe_allow_html=True,
        )
        return

    # ── 第二步 ──
    st.markdown("---")
    st.markdown(
        '<div class="step-num">2</div> <b>下载结果文件</b>',
        unsafe_allow_html=True,
    )

    icao = ap.icao or "AIRPORT"
    qfu_h = {}
    for rwy in ap.runways:
        for q in rwy.qfus:
            if q.magnetic_heading:
                qfu_h[q.ident] = float(q.magnetic_heading)

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**📊 Excel 分析报表 (XLSX)**")
        st.caption("含完整计算公式、彩色标注，可用 Excel 打开核验")
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                generate_xlsx(ap, tmp.name, qfu_h)
                xlsx_path = tmp.name
            with open(xlsx_path, "rb") as f:
                st.download_button(
                    "⬇️ 下载 XLSX",
                    f.read(),
                    file_name=f"{icao}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            os.unlink(xlsx_path)
        except Exception as e:
            st.error(f"XLSX 生成失败: {e}")

    with c2:
        st.markdown("**📝 PEP 格式 TXT**")
        st.caption("标准 PEP 格式，可直接导入 PEP 系统")
        try:
            txt = generate_txt(ap)
            st.download_button(
                "⬇️ 下载 TXT",
                txt.encode("utf-8"),
                file_name=f"{icao}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"TXT 生成失败: {e}")

    # 预览
    st.markdown("---")
    with st.expander("📄 预览 TXT 输出内容", expanded=False):
        try:
            st.code(generate_txt(ap), language="text")
        except Exception as e:
            st.error(str(e))


# ═══════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════
def main():
    # 标题
    st.markdown(
        '<div class="main-header">'
        "<h1>✈ 机场障碍物对飞行影响分析系统</h1>"
        "<p>AIRPORT OBSTACLE IMPACT ANALYSIS SYSTEM · ICAO Annex 14 / PANS-OPS</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    sidebar()

    if st.session_state.airport is None:
        welcome()
    else:
        ap = st.session_state.airport
        t1, t2, t3, t4, t5, t6 = st.tabs([
            "🏛️ 机场信息",
            "🛤️ 跑道/QFU",
            "🗼 障碍物",
            "✈️ 离场参数",
            "📊 分析结果",
            "💾 导出",
        ])
        with t1:
            tab_airport(ap)
        with t2:
            tab_runway(ap)
        with t3:
            tab_obstacle(ap)
        with t4:
            tab_departure(ap)
        with t5:
            tab_results(ap)
        with t6:
            tab_export(ap)


if __name__ == "__main__":
    main()
