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
from core.geometry import compute_obstacle_results, compute_ht_ft, apply_shielding
from core.xlsx_writer import generate_xlsx
from core.txt_writer import write_txt, generate_txt
from templates.constants import M_TO_FT
from usage_tracker import track_visit_once, track_event, maybe_render_admin

# ══════════════════════════════════════════════════════════════════
# 版本号 — 语义化版本规则 (大厂通行: MAJOR.MINOR.PATCH)
#   v1.0.0  首次发布
#   v1.0.1  ApproachSlope/PEP round-trip 修复
#   v1.1.0  UI 重构: 步骤卡片, 主按钮高亮, 作者信息, 版本徽标; 移除 PEP TXT 导入入口
# ══════════════════════════════════════════════════════════════════
APP_VERSION = "V 1.3.4"
AUTHOR = "王迪"
TECH_SUPPORT = "邵小隆"

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
    :root {
        --bg: #0a0e17;
        --panel: #0d1520;
        --panel-strong: #0d2137;
        --line: #1a3a5c;
        --line-strong: #1a5276;
        --accent: #4fc3f7;
        --accent-soft: #80d0f8;
        --text: #c0d8f0;
        --muted: #6d93b2;
        --ok: #66bb6a;
        --warn: #ffb74d;
    }
    html, body, [class*="css"] {
        font-family: "Menlo", "Consolas", "SF Mono", "Monaco", monospace;
        color: var(--text);
    }
    .stApp {
        background: radial-gradient(circle at 100% -5%, #113052 0%, var(--bg) 35%);
    }
    .main .block-container {
        max-width: 1400px;
        padding-top: 1.1rem;
        padding-bottom: 1.2rem;
    }
    .main-header {
        position: relative;
        text-align: center;
        padding: 0.8rem 0 0.4rem 0;
        border-bottom: 1px solid var(--line);
        margin-bottom: 0.8rem;
    }
    .main-header h1 {
        color: var(--accent);
        margin: 0;
        letter-spacing: 2px;
        font-size: 1.75rem;
        font-weight: 700;
    }
    .main-header p {
        color: var(--muted);
        margin: 0.2rem 0 0 0;
        font-size: 0.8rem;
        letter-spacing: 1px;
    }
    /* ── 右上角作者+版本徽标 ── */
    .header-meta {
        position: absolute;
        top: 6px;
        right: 8px;
        text-align: right;
        line-height: 1.55;
    }
    .header-meta .badge-version {
        display: inline-block;
        background: transparent;
        color: #50fa7b;
        border: 1px solid #50fa7b;
        border-radius: 12px;
        padding: 2px 14px;
        font-size: 0.78rem;
        font-weight: 700;
        font-family: "Menlo", monospace;
        letter-spacing: 2px;
        margin-bottom: 12px;
    }
    .header-meta table.credits {
        margin-left: auto;
        border-collapse: collapse;
    }
    .header-meta table.credits td {
        color: #4fc3f7;
        font-size: 0.78rem;
        font-weight: 700;
        font-family: "Menlo", monospace;
        letter-spacing: 1px;
        padding: 2px 0;
    }
    .header-meta table.credits td.t-label { text-align: right; padding-right: 2px; }
    .header-meta table.credits td.t-colon { text-align: center; padding: 0 2px; }
    .header-meta table.credits td.t-name  { text-align: left;  padding-left: 2px; }
    .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 0.85rem 1rem;
        margin: 0.35rem 0;
    }
    .panel-title {
        color: var(--accent);
        font-weight: 700;
        margin-bottom: 0.4rem;
        letter-spacing: 0.4px;
    }
    .quick-guide {
        color: var(--text);
        line-height: 1.65;
        font-size: 0.84rem;
        white-space: pre-line;
    }
    .status-strip {
        margin-top: 0.4rem;
        color: var(--muted);
        font-size: 0.76rem;
        border-top: 1px dashed var(--line);
        padding-top: 0.35rem;
    }
    .info-box, .warn-box, .ok-box {
        border-radius: 5px;
        padding: 0.7rem 0.9rem;
        margin: 0.35rem 0;
        border-left: 3px solid var(--accent);
        background: var(--panel-strong);
        font-size: 0.84rem;
    }
    .warn-box {
        border-left-color: var(--warn);
        color: #e0c890;
        background: #1b1a10;
    }
    .ok-box {
        border-left-color: var(--ok);
        color: #aadab0;
        background: #0f1f17;
    }
    .step-num {
        display: inline-block;
        background: var(--accent);
        color: var(--bg);
        width: 26px;
        height: 26px;
        border-radius: 999px;
        text-align: center;
        line-height: 26px;
        font-weight: 700;
        margin-right: 8px;
    }
    section[data-testid="stSidebar"] {
        border-right: 1px solid var(--line);
    }
    section[data-testid="stSidebar"] > div {
        background: var(--panel);
    }
    .stButton > button,
    .stDownloadButton > button {
        background: var(--panel-strong) !important;
        color: var(--accent) !important;
        border: 1px solid var(--line-strong) !important;
        border-radius: 4px !important;
        min-height: 2.2rem;
    }
    .stButton > button:hover,
    .stDownloadButton > button:hover {
        border-color: var(--accent) !important;
        background: #153d5e !important;
    }
    button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(180deg, #1d6f3a 0%, #155a2c 100%) !important;
        color: #f0fff4 !important;
        border: 2px solid #50fa7b !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        min-height: 2.8rem !important;
        letter-spacing: 1px !important;
        box-shadow: 0 0 12px rgba(80, 250, 123, 0.25) !important;
    }
    button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(180deg, #2a9050 0%, #1a7a3a 100%) !important;
        border-color: #88ffaa !important;
        box-shadow: 0 0 16px rgba(80, 250, 123, 0.45) !important;
    }
    /* 文件上传器突出显示 (主操作) */
    [data-testid="stFileUploader"] {
        border: 2px dashed #4fc3f7 !important;
        border-radius: 8px !important;
        background: #0d2137 !important;
        padding: 4px;
        box-shadow: 0 0 8px rgba(79, 195, 247, 0.2);
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #80d0f8 !important;
        box-shadow: 0 0 14px rgba(79, 195, 247, 0.4);
    }
    /* ── 步骤卡片 (操作指南) ── */
    .step-card {
        background: linear-gradient(180deg, #0d1d30 0%, #0a1726 100%);
        border: 1px solid #1a4a6c;
        border-radius: 8px;
        padding: 14px 14px 12px 14px;
        height: 100%;
        min-height: 130px;
        position: relative;
        transition: border-color 0.2s;
    }
    .step-card:hover {
        border-color: var(--accent);
    }
    .step-card .step-head {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }
    .step-card .step-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px; height: 28px;
        border-radius: 50%;
        background: var(--accent);
        color: var(--bg);
        font-weight: 800;
        font-size: 14px;
        flex-shrink: 0;
    }
    .step-card .step-title {
        color: var(--accent);
        font-weight: 700;
        font-size: 0.95rem;
        letter-spacing: 0.5px;
    }
    .step-card .step-desc {
        color: #8ab4d4;
        font-size: 0.78rem;
        line-height: 1.55;
    }
    .stTabs [data-baseweb="tab-list"] {
        background: transparent;
        border-bottom: 1px solid var(--line);
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--muted);
        border: 1px solid transparent;
        border-bottom: none;
        border-radius: 6px 6px 0 0;
        padding: 0.5rem 1rem;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--accent-soft);
        background: #122a42;
    }
    .stTabs [aria-selected="true"] {
        color: var(--accent) !important;
        background: var(--panel-strong) !important;
        border-color: var(--line) !important;
        border-bottom: 2px solid var(--accent) !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background: var(--panel);
        border: 1px solid var(--line);
        border-top: none;
        border-radius: 0 0 6px 6px;
        padding: 1rem;
    }
    [data-testid="stMetric"] {
        background: var(--panel-strong);
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 0.65rem 0.8rem;
    }
    [data-testid="stMetricLabel"] {
        color: var(--muted) !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--accent) !important;
    }
    details {
        border: 1px solid var(--line) !important;
        border-radius: 6px !important;
        background: var(--panel) !important;
    }
    details summary {
        background: var(--panel-strong) !important;
        color: var(--accent) !important;
        border-radius: 6px 6px 0 0;
    }
    .stSelectbox > div > div,
    .stNumberInput > div > div > input,
    .stTextInput > div > div > input,
    .stTextArea textarea {
        background: #0d1a28 !important;
        color: var(--text) !important;
        border-color: var(--line) !important;
    }
    .stSelectbox > div > div:focus-within,
    .stNumberInput > div > div > input:focus,
    .stTextInput > div > div > input:focus,
    .stTextArea textarea:focus {
        border-color: var(--accent) !important;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 4px;
    }
    .stAlert > div[data-baseweb="notification"] {
        background: #0d1a28 !important;
        border: 1px solid var(--line) !important;
    }
    h1, h2, h3, h4, h5, h6 {
        color: var(--accent) !important;
    }
    h3 {
        border-bottom: 1px solid var(--line);
        padding-bottom: 0.35rem;
        margin-bottom: 0.7rem;
    }
    .stCaption, small {
        color: #4e7493 !important;
    }
    code, .stCodeBlock {
        background: #0a1018 !important;
        color: #86b7d7 !important;
    }
    hr {
        border-color: var(--line) !important;
    }
    a { color: var(--accent) !important; }
    a:hover { color: var(--accent-soft) !important; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: #0a1018; }
    ::-webkit-scrollbar-thumb { background: #1a3a5c; border-radius: 5px; }
    ::-webkit-scrollbar-thumb:hover { background: #2a5a8c; }
    .footer-credit {
        text-align: center;
        color: #3a6080;
        font-size: 0.72rem;
        padding: 8px 0;
        border-top: 1px solid var(--line);
        margin-top: 0.8rem;
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
    """自动识别文件类型并解析为 Airport 对象。
    支持: AIP PDF / AIP TXT (不再支持 PEP TXT 导入)。"""
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
            raise ValueError(
                "检测到 PEP TXT 文件。当前版本已移除 PEP TXT 导入功能，"
                "请上传 AIP PDF 或 AIP TXT 原始数据文件。"
            )
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
        st.markdown("### 数据导入控制台")
        st.markdown(
            '<div class="info-box">'
            "<b>支持格式</b><br>"
            "AIP PDF（推荐） / AIP TXT<br>"
            "<small>系统自动识别并解析，无需手动选择类型</small>"
            "</div>",
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "上传数据文件",
            type=["txt", "pdf"],
            help="点击或拖拽上传 AIP PDF / AIP TXT",
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
                        track_event(
                            "upload",
                            file=uploaded.name,
                            size_kb=round(uploaded.size / 1024, 1),
                            method=method,
                            icao=getattr(ap, "icao", "?"),
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 解析失败: {e}")
                        st.code(traceback.format_exc(), language="text")

        # 当前数据状态
        if st.session_state.airport:
            ap = st.session_state.airport
            st.markdown("---")
            st.markdown("### 当前数据状态")
            st.markdown(
                f"- **机场** {ap.icao} — {ap.name}\n"
                f"- **跑道** {len(ap.runways)} 条\n"
                f"- **障碍物** {len(ap.obstacles)} 个\n"
                f"- **状态** {'✅ 已计算' if st.session_state.computed else '⏳ 待计算'}"
            )

        # ── 资源下载 ──
        st.markdown("---")
        st.markdown("### 资源下载")

        _download_btn("📖 使用说明书 (MD)", "使用说明书.md", "text/markdown", "manual.md")
        _download_btn("📄 使用说明书 (Word)", "使用说明书.docx",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "manual.docx")
        _download_btn("📊 系统介绍PPT", "机场障碍物分析系统介绍.pptx",
                      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                      "intro.pptx")

        # ── 演示视频 ──
        st.markdown("---")
        st.markdown("### 操作演示")
        vpath = os.path.join(RES, "机场障碍物分析演示.mp4")
        if not os.path.exists(vpath):
            vpath = os.path.join(RES, "demo.mp4")
        if os.path.exists(vpath):
            st.video(vpath)

        st.markdown("---")
        st.markdown(
            f'<p class="footer-credit">'
            f"{APP_VERSION} · 开发设计：{AUTHOR} · 技术支持：{TECH_SUPPORT}</p>",
            unsafe_allow_html=True,
        )


def _download_btn(label, fname, mime, alt_fname=None):
    fpath = os.path.join(RES, fname)
    if not os.path.exists(fpath) and alt_fname:
        fpath = os.path.join(RES, alt_fname)
    if os.path.exists(fpath):
        with open(fpath, "rb") as f:
            st.download_button(label, f.read(), file_name=fname, mime=mime,
                               use_container_width=True)


# ═══════════════════════════════════════════════════════════
# 欢迎页
# ═══════════════════════════════════════════════════════════
def welcome():
    st.markdown("### 操作指南 · QUICK START GUIDE")
    st.markdown(
        """
<div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin: 4px 0 18px 0;">
  <div class="step-card">
    <div class="step-head"><div class="step-badge">1</div><div class="step-title">导入数据</div></div>
    <div class="step-desc">在左侧上传 <b>AIP PDF</b> 或 <b>AIP TXT</b>，系统自动识别格式并解析。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">2</div><div class="step-title">核对信息</div></div>
    <div class="step-desc">在「机场信息 / 跑道·QFU / 障碍物」页签核对解析结果，可直接在表格中修改。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">3</div><div class="step-title">设置离场</div></div>
    <div class="step-desc">在「离场参数」页签为各 QFU 配置离场转弯角和坐标偏移参数。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">4</div><div class="step-title">计算导出</div></div>
    <div class="step-desc">在「导出」页签点击 <b>计算分析</b>，下载 <b>XLSX + TXT</b> 分析报告。</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            '<div class="panel">'
            '<div class="panel-title">支持格式</div>'
            'AIP PDF（推荐）<br>'
            'AIP TXT'
            '</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="panel">'
            '<div class="panel-title">核心能力</div>'
            '自动解析机场/跑道/障碍物数据<br>'
            'ICAO 标准梯度面计算与遮蔽判定<br>'
            '导出 Excel + PEP TXT'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="ok-box">SYSTEM READY · 请从左侧导入 AIP 数据文件开始分析</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════
# 数据同步辅助函数 (data_editor → 模型对象)
# ═══════════════════════════════════════════════════════════
def _safe_int(v, d=0):
    """安全转换为int"""
    if v is None:
        return d
    try:
        f = float(v)
        return d if math.isnan(f) else int(f)
    except (ValueError, TypeError):
        return d


def _safe_float(v, d=0.0):
    """安全转换为float"""
    if v is None:
        return d
    try:
        f = float(v)
        return d if math.isnan(f) else f
    except (ValueError, TypeError):
        return d


def _sync_qfus(rwy, edited_df):
    """将编辑后的QFU DataFrame同步回Runway.qfus"""
    orig_count = len(rwy.qfus)
    new_qfus = []
    for idx, row in edited_df.iterrows():
        ident = str(row.get("方向", "")).strip()
        if not ident:
            continue
        mh = _safe_int(row.get("磁方位°"))
        tora = _safe_int(row.get("TORA"))
        toda = _safe_int(row.get("TODA"))
        asda = _safe_int(row.get("ASDA"))
        lda = _safe_int(row.get("LDA"))
        te = _safe_float(row.get("入口标高m"))
        slope = _safe_float(row.get("坡度%"))
        gs_raw = _safe_float(row.get("GlideSlope"))
        gs_val = gs_raw if gs_raw != 0.0 else None
        is_inter = bool(row.get("交叉起飞点", False))

        if 0 <= idx < orig_count:
            q = rwy.qfus[idx]
            q.ident, q.magnetic_heading = ident, mh
            q.tora, q.toda, q.asda, q.lda = tora, toda, asda, lda
            q.threshold_elevation, q.slope = te, slope
            q.glide_slope = gs_val
            q.ga_method_flag = 0 if gs_val else 1
            q.is_intersection = is_inter
            new_qfus.append(q)
        else:
            new_qfus.append(QFU(
                ident=ident, magnetic_heading=mh,
                tora=tora, toda=toda, asda=asda, lda=lda,
                threshold_elevation=te, slope=slope,
                glide_slope=gs_val,
                ga_method_flag=0 if gs_val else 1,
                is_intersection=is_inter,
            ))
    rwy.qfus = new_qfus


def _sync_obstacles(ap, edited_df):
    """将编辑后的障碍物DataFrame同步回Airport.obstacles"""
    orig_count = len(ap.obstacles)
    new_obs = []
    for idx, row in edited_df.iterrows():
        name = str(row.get("名称", "") or "").strip()
        seq = _safe_int(row.get("序号"))
        dist = _safe_int(row.get("距离m"))
        if not name and seq == 0 and dist == 0:
            continue
        bearing = _safe_int(row.get("磁方位°"))
        elev = _safe_float(row.get("海拔m"))
        coord = str(row.get("坐标", "") or "")
        ctrl = str(row.get("控制障碍物", "") or "")
        note = str(row.get("备注", "") or "")

        if 0 <= idx < orig_count:
            o = ap.obstacles[idx]
            o.seq, o.name = seq, name
            o.bearing, o.distance = bearing, dist
            o.coordinate, o.elevation_m = coord, elev
            o.remark_control, o.note = ctrl, note
            new_obs.append(o)
        else:
            new_obs.append(Obstacle(
                seq=seq or (len(new_obs) + 1),
                name=name, bearing=bearing, distance=dist,
                coordinate=coord, elevation_m=elev,
                remark_control=ctrl, note=note,
            ))
    ap.obstacles = new_obs


def _sync_results(qfu, edited_df):
    """将编辑后的分析结果DataFrame同步回QFU.obstacle_results"""
    for idx, row in edited_df.iterrows():
        if idx >= len(qfu.obstacle_results):
            break
        r = qfu.obstacle_results[idx]
        tag = str(row.get("判定", ""))
        if "有效" in tag:
            r.is_obstacle, r.is_shielded = True, False
        elif "遮蔽" in tag:
            r.is_obstacle, r.is_shielded = True, True
        else:
            r.is_obstacle, r.is_shielded = False, False
        r.comment_label = str(row.get("标注", "") or "")


# ═══════════════════════════════════════════════════════════
# Tab 1: 机场信息
# ═══════════════════════════════════════════════════════════
def tab_airport(ap: Airport):
    st.markdown("### 机场基本信息")
    iid = st.session_state.imp_id

    c1, c2, c3, c4 = st.columns(4)
    ap.icao = c1.text_input("ICAO", value=ap.icao or "", key=f"ap_icao_{iid}")
    ap.iata = c2.text_input("IATA", value=ap.iata or "", key=f"ap_iata_{iid}")
    ap.elevation = c3.number_input(
        "标高(m)", value=float(ap.elevation or 0), step=0.1,
        format="%.1f", key=f"ap_elev_{iid}")
    ap.magnetic_variation = c4.text_input(
        "磁差", value=ap.magnetic_variation or "", key=f"ap_magvar_{iid}")

    st.markdown("---")
    c1, c2 = st.columns(2)
    ap.name = c1.text_input("名称", value=ap.name or "", key=f"ap_name_{iid}")
    ap.city = c1.text_input("城市", value=ap.city or "", key=f"ap_city_{iid}")
    ap.last_update = c2.text_input(
        "数据日期", value=ap.last_update or "", key=f"ap_lupd_{iid}")
    ap.obstacle_last_update = c2.text_input(
        "障碍物日期", value=ap.obstacle_last_update or "", key=f"ap_olupd_{iid}")

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

    st.markdown("### 跑道 / QFU 数据")
    st.caption("编辑表格可直接修改数据 · 点击表格下方 ➕ 可新增 QFU · GlideSlope 填0表示无ILS")
    iid = st.session_state.imp_id

    for ri, rwy in enumerate(ap.runways):
        with st.expander(f"跑道 {ri+1}", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            rwy.max_length = c1.number_input(
                "长度(m)", value=rwy.max_length, step=1,
                key=f"rwy_len_{ri}_{iid}")
            rwy.width = c2.number_input(
                "宽度(m)", value=rwy.width, step=1,
                key=f"rwy_wid_{ri}_{iid}")
            rwy.magnetic_heading = c3.number_input(
                "跑道磁方位°", value=rwy.magnetic_heading, step=1,
                key=f"rwy_mh_{ri}_{iid}")
            rwy.strength = c4.text_input(
                "PCN", value=rwy.strength or "",
                key=f"rwy_pcn_{ri}_{iid}")

            st.markdown("**QFU 方向数据**")
            rows = []
            for q in rwy.qfus:
                rows.append({
                    "方向": q.ident,
                    "磁方位°": q.magnetic_heading,
                    "TORA": q.tora,
                    "TODA": q.toda,
                    "ASDA": q.asda,
                    "LDA": q.lda,
                    "入口标高m": round(q.threshold_elevation, 1),
                    "坡度%": round(q.slope, 2),
                    "GlideSlope": q.glide_slope if q.glide_slope is not None else 0.0,
                    "交叉起飞点": q.is_intersection,
                })
            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["方向", "磁方位°", "TORA", "TODA", "ASDA", "LDA",
                         "入口标高m", "坡度%", "GlideSlope", "交叉起飞点"])

            edited_df = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"qfu_edit_{ri}_{iid}",
                column_config={
                    "GlideSlope": st.column_config.NumberColumn(
                        "GlideSlope", help="ILS下滑角(如-3)，无ILS填0",
                        format="%.1f"),
                    "坡度%": st.column_config.NumberColumn(
                        "坡度%", format="%.2f"),
                    "入口标高m": st.column_config.NumberColumn(
                        "入口标高m", format="%.1f"),
                },
            )

            _sync_qfus(rwy, edited_df)


# ═══════════════════════════════════════════════════════════
# Tab 3: 障碍物
# ═══════════════════════════════════════════════════════════
def tab_obstacle(ap: Airport):
    import pandas as pd

    st.markdown("### 障碍物数据 (AD 2.10)")
    st.caption("编辑表格可直接修改数据 · 点击表格下方 ➕ 可新增障碍物")
    iid = st.session_state.imp_id

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
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["序号", "名称", "磁方位°", "距离m", "坐标", "海拔m", "控制障碍物", "备注"])

    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=450,
        key=f"obs_edit_{iid}",
        column_config={
            "海拔m": st.column_config.NumberColumn("海拔m", format="%.1f"),
        },
    )

    _sync_obstacles(ap, edited_df)
    st.caption(f"共 {len(ap.obstacles)} 个障碍物")


# ═══════════════════════════════════════════════════════════
# Tab 4: 离场参数
# ═══════════════════════════════════════════════════════════
def tab_departure(ap: Airport):
    st.markdown("### 离场参数设置")

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

    st.markdown("### 分析结果")
    st.caption("可修改「判定」和「标注」列 · 修改后导出文件将反映更改")

    if not st.session_state.computed:
        st.info("⏳ 请先在「💾 导出」页签点击 **计算分析** 按钮")
        return

    iid = st.session_state.imp_id

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

                edited_df = st.data_editor(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    key=f"res_{qfu.ident}_{iid}",
                    column_config={
                        "判定": st.column_config.SelectboxColumn(
                            "判定",
                            options=["🔴 有效障碍物", "⚪ 被遮蔽", "🔵 非障碍物"],
                            required=True,
                        ),
                    },
                    disabled=["序号", "名称", "DIST(m)", "HT(m)", "HT(ft)"],
                )

                _sync_results(qfu, edited_df)

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
    st.markdown("### 计算与导出")

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

    # 主操作按钮 — 居中突出
    c_l, c_m, c_r = st.columns([1, 2, 1])
    with c_m:
        btn = st.button(
            "🚀  计算分析" if not st.session_state.computed else "🔄  重新计算分析",
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
                track_event(
                    "compute",
                    icao=getattr(ap, "icao", "?"),
                    runways=len(ap.runways),
                    obstacles=len(ap.obstacles),
                )
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
                xlsx_bytes = f.read()
            if st.download_button(
                "⬇️ 下载 XLSX",
                xlsx_bytes,
                file_name=f"{icao}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            ):
                track_event("export", fmt="xlsx", icao=icao)
            os.unlink(xlsx_path)
        except Exception as e:
            st.error(f"XLSX 生成失败: {e}")

    with c2:
        st.markdown("**📝 PEP 格式 TXT**")
        st.caption("标准 PEP 格式，可直接导入 PEP 系统")
        try:
            txt = generate_txt(ap)
            if st.download_button(
                "⬇️ 下载 TXT",
                txt.encode("utf-8"),
                file_name=f"{icao}.txt",
                mime="text/plain",
                use_container_width=True,
            ):
                track_event("export", fmt="txt", icao=icao)
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
    # ── 隐蔽访问追踪（管理员页 / 普通访客自动记录）──
    if maybe_render_admin():
        return
    track_visit_once()

    # 标题 (含右上角作者+版本徽标)
    st.markdown(
        f"""
<div class="main-header">
    <div class="header-meta">
        <div class="badge-version">{APP_VERSION}</div>
        <table class="credits">
            <tr>
                <td class="t-label">开发设计</td>
                <td class="t-colon">：</td>
                <td class="t-name">{AUTHOR}</td>
            </tr>
            <tr>
                <td class="t-label">技术支持</td>
                <td class="t-colon">：</td>
                <td class="t-name">{TECH_SUPPORT}</td>
            </tr>
        </table>
    </div>
    <h1>✈ 机场障碍物对飞行影响分析系统</h1>
    <p>AIRPORT OBSTACLE IMPACT ANALYSIS SYSTEM · ICAO Annex 14 / PANS-OPS</p>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin: 6px 0 14px 0;">
  <div class="step-card">
    <div class="step-head"><div class="step-badge">1</div><div class="step-title">导入数据</div></div>
    <div class="step-desc">在左侧上传 <b>AIP PDF</b> 或 <b>AIP TXT</b> 原始数据文件，系统自动识别并解析。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">2</div><div class="step-title">核对信息</div></div>
    <div class="step-desc">查看「机场信息」「跑道/QFU」「障碍物」页签，按需直接在表格中修正。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">3</div><div class="step-title">设置离场</div></div>
    <div class="step-desc">在「离场参数」页签为各 QFU 配置离场转弯角和坐标偏移。</div>
  </div>
  <div class="step-card">
    <div class="step-head"><div class="step-badge">4</div><div class="step-title">计算导出</div></div>
    <div class="step-desc">进入「导出」页签点击 <b>计算分析</b>，下载 <b>XLSX + TXT</b> 报告。</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    sidebar()

    if st.session_state.airport is None:
        welcome()
    else:
        ap = st.session_state.airport
        t1, t2, t3, t4, t5, t6 = st.tabs([
            "机场信息",
            "跑道/QFU",
            "障碍物",
            "离场参数",
            "分析结果",
            "导出",
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
