import streamlit as st
import pandas as pd

st.set_page_config(page_title="机场障碍物分析系统 - 样式优化测试版", layout="wide", initial_sidebar_state="expanded")

# --- 核心显示层优化 CSS ---
st.markdown("""
<style>
/* 1. 更柔和、护眼的深空灰背景 */
.stApp {
    background-color: #0d1117; /* GitHub Dark Base */
    color: #c9d1d9;
}

/* 2. 侧边栏及分隔线柔化 */
section[data-testid="stSidebar"] {
    background-color: #010409 !important;
    border-right: 1px solid #30363d;
}
hr {
    border-color: #30363d !important;
}

/* 3. 字体层次强化 */
h1, h2, h3, h4 {
    font-weight: 600 !important;
    color: #e6edf3 !important;
    letter-spacing: -0.5px !important;
}

/* 4. 原生 Button 样式覆写（去掉粗粝的边框线，增加灵动悬浮）*/
.stButton > button, .stDownloadButton > button {
    background-color: #21262d !important;
    border: 1px solid #30363d !important;
    color: #c9d1d9 !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background-color: #30363d !important;
    border-color: #8b949e !important;
    color: #ffffff !important;
}
button[data-testid="stBaseButton-primary"] {
    background-color: #238636 !important; /* GitHub 经典通过绿色 */
    border: 1px solid rgba(240, 246, 252, 0.1) !important;
    color: white !important;
}
button[data-testid="stBaseButton-primary"]:hover {
    background-color: #2ea043 !important;
}

/* 5. 原生步骤小卡片(保留原布局，但更美观) */
.status-strip {
    background-color: #161b22; 
    border: 1px solid #30363d; 
    border-radius: 8px; 
    padding: 18px 24px; 
    margin-bottom: 24px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

/* 6. DataFrame 原生表格渲染注入 */
[data-testid="stDataFrame"] {
    border: 1px solid #30363d;
    border-radius: 8px;
    overflow: hidden;
}
</style>
""", unsafe_allow_html=True)

# ---> 以下严格保持与原线上版本类似的排版 <---

# 侧边栏布局
with st.sidebar:
    st.markdown("### ✈️ 分析系统控制台")
    st.info("当前模式：纯 UI 样式注入测试（静态 mock 不跑逻辑）", icon="🎨")
    st.file_uploader("📥 第一步：导入 AIP PDF (支持拖拽)", type=["pdf"])
    st.number_input("安全阈值 / Threshold", value=5.0)
    st.markdown("---")
    st.button("⚙️ 重新分析所有障碍物", type="primary", width="stretch")

# 主界面布局
st.title("机场障碍物对飞行影响分析系统")
st.markdown("基于 ICAO Annex 14 / PANS-OPS 标准")

# 模拟原始版本的状态卡片
st.markdown("""
<div class="status-strip">
    <h4 style="margin-top:0;">✅ 已就绪: 机场 ZBAA</h4>
    <span style="color:#8b949e; font-size:14px;">主跑道长度: 3800m | 识别障碍物: 42 项</span>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["🏛 机场", "🛣 跑道", "🗼 障碍物", "📊 分析报表"])

with tab1:
    st.markdown("### 基础参数核对")
    c1, c2 = st.columns(2)
    c1.text_input("机场四字码 (ICAO)", "ZBAA")
    c2.number_input("机场基准标高 (ft)", value=116)
    
with tab4:
    st.markdown("### 覆盖限面分析结果")
    df_res = pd.DataFrame({
        "障碍物编号": ["OBS-01", "OBS-02", "OBS-03", "OBS-04"],
        "类型": ["塔吊", "烟囱", "建筑", "山体"],
        "高度(ft)": [500, 480, 200, 1200],
        "穿越限面": ["OAS超限", "安全", "安全", "起飞面超限"],
        "权重验证": ["危险", "正常", "正常", "危险"]
    })
    
    # 使用 Pandas 原生的背景颜色标记，适配护眼主题
    def soft_highlight(val):
        if val == '危险': return 'color: #ff7b72; background-color: rgba(255, 123, 114, 0.1);'
        if val == '正常': return 'color: #56d364; background-color: rgba(86, 211, 100, 0.1);'
        return ''
        
    st.dataframe(df_res.style.map(soft_highlight, subset=['权重验证']), width="stretch", hide_index=True)
    
    c1, c2 = st.columns(2)
    c1.button("下载 PEP 数据包 (TXT)", width="stretch")
    c2.button("导出报表 (XLSX)", type="primary", width="stretch")

