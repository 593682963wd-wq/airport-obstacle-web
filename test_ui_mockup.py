import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="✈ 机场障碍物分析系统 - 概念 UI 测试", layout="wide", initial_sidebar_state="expanded")

# --- CSS 注入: 现代航空/仪表盘风格 ---
st.markdown("""
<style>
/* 全局暗色高级背景 */
.stApp {
    background: radial-gradient(circle at 10% 20%, #0d121c 0%, #06080d 100%);
    color: #e0e6ed;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* 玻璃拟态风格卡片 */
.glass-card {
    background: rgba(22, 34, 53, 0.6);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(79, 195, 247, 0.15);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    transition: transform 0.2s, box-shadow 0.2s;
}
.glass-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 40px 0 rgba(79, 195, 247, 0.1);
    border: 1px solid rgba(79, 195, 247, 0.3);
}

/* 数据指标大字 */
.metric-value {
    font-size: 2.2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #4fc3f7, #64ffda);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
    line-height: 1.2;
}
.metric-label {
    font-size: 0.9rem;
    color: #8a9bb2;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 5px;
}

/* 定制的主按钮 */
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #0277bd, #00838f) !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 10px 24px !important;
    box-shadow: 0 4px 15px rgba(2, 119, 189, 0.4) !important;
}
button[data-testid="baseButton-primary"]:hover {
    box-shadow: 0 6px 20px rgba(2, 119, 189, 0.6) !important;
    transform: scale(1.02);
}

/* 进度条节点 */
.stepper-container {
    display: flex;
    justify-content: space-between;
    margin-bottom: 30px;
    padding: 15px;
    background: rgba(13, 33, 55, 0.4);
    border-radius: 12px;
}
.step {
    text-align: center;
    flex: 1;
    position: relative;
}
.step-circle {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #1a3a5c;
    color: #4fc3f7;
    line-height: 32px;
    margin: 0 auto;
    font-weight: bold;
    z-index: 2;
    position: relative;
    border: 2px solid transparent;
}
.step.active .step-circle {
    background: #0277bd;
    color: white;
    border: 2px solid #4fc3f7;
    box-shadow: 0 0 15px rgba(79, 195, 247, 0.5);
}
.step-label {
    margin-top: 8px;
    font-size: 0.85rem;
    color: #8a9bb2;
}
.step.active .step-label {
    color: #4fc3f7;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# --- 模拟状态 ---
if "current_step" not in st.session_state:
    st.session_state.current_step = 1

st.title("🛩️ 机场障碍物分析系统 UI测试版")
st.caption("Aviation Obstacle Analytics Dashboard - Concept Demo")

# --- 步骤条 ---
steps = ["1. 上传与解析", "2. 数据面板", "3. 航向设定", "4. 深度报告"]
stepper_html = "<div class='stepper-container'>"
for i, name in enumerate(steps, 1):
    active = "active" if i == st.session_state.current_step else ""
    stepper_html += f"""
    <div class='step {active}'>
        <div class='step-circle'>{i}</div>
        <div class='step-label'>{name}</div>
    </div>
    """
stepper_html += "</div>"
st.markdown(stepper_html, unsafe_allow_html=True)

# --- 侧边栏 ---
with st.sidebar:
    st.image("https://img.icons8.com/color/150/airport.png", width=60)
    st.markdown("### 控制台")
    st.info("当前模式：模拟演示 (不修改实际核心逻辑)")
    
    st.divider()
    st.markdown("#### 导航控制")
    # 模拟切换页面
    if st.button("前一步", disabled=(st.session_state.current_step <= 1), use_container_width=True):
        st.session_state.current_step -= 1
        st.rerun()
    if st.button("下一步骤", type="primary", disabled=(st.session_state.current_step >= 4), use_container_width=True):
        st.session_state.current_step += 1
        st.rerun()

# --- 页面内容 ---
if st.session_state.current_step == 1:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("""
        <div class='glass-card'>
            <h4>📄 导入 AIP 数据</h4>
            <p style='color: #8a9bb2;'>支持国家标准航行资料汇编 PDF，系统将自动高精度提取跑道和障碍物参数。</p>
        </div>
        """, unsafe_allow_html=True)
        st.file_uploader("上传机场 AIP PDF 文件", type=['pdf'], label_visibility="collapsed")
    with col2:
        st.markdown("""
        <div class='glass-card'>
            <h4>⚙️ 处理日志</h4>
            <code style='color: #64ffda; background: transparent;'>
            > 等待文件输入...<br>
            > 系统引擎已就绪 🟢<br>
            > 内存安全沙箱已开启
            </code>
        </div>
        """, unsafe_allow_html=True)

elif st.session_state.current_step == 2:
    st.markdown("### 📊 机场概况仪表盘")
    # 核心指标区
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown("<div class='glass-card'><div class='metric-value'>ZBAA</div><div class='metric-label'>四字代码 / ICAO</div></div>", unsafe_allow_html=True)
    c2.markdown("<div class='glass-card'><div class='metric-value'>3800m</div><div class='metric-label'>主跑道长度 / RWY</div></div>", unsafe_allow_html=True)
    c3.markdown("<div class='glass-card'><div class='metric-value'>42</div><div class='metric-label'>监测障碍物 / OBS</div></div>", unsafe_allow_html=True)
    c4.markdown("<div class='glass-card'><div class='metric-value'>116ft</div><div class='metric-label'>机场基准标高 / ELEV</div></div>", unsafe_allow_html=True)
    
    st.markdown("#### 跑道参数预览 (Mock)")
    df = pd.DataFrame({
        "QFU": ["18L", "36R", "18R", "36L"],
        "TODA (m)": [3800, 3800, 3800, 3800],
        "标高 (m)": [35.35, 35.35, 35.35, 35.35],
        "坡度 (%)": [-0.03, 0.03, -0.05, 0.05]
    })
    st.dataframe(df, use_container_width=True, hide_index=True)

elif st.session_state.current_step == 3:
    st.markdown("""
    <div class='glass-card'>
        <h4>🧭 设定离场转弯属性</h4>
        <p>为各跑道配置起飞航向角与偏置参数，用于扇区覆盖计算。</p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.expander("QFU: 18L 配置", expanded=True):
        st.slider("直线段长度 (m)", 0, 5000, 1500)
        st.number_input("左转角度 (°)", 0, 180, 15)
        st.number_input("右转角度 (°)", 0, 180, 15)
        
elif st.session_state.current_step == 4:
    st.markdown("### 🏆 最终覆盖性分析报表")
    
    # 模拟结果高亮亮色
    df_res = pd.DataFrame({
        "障碍物编号": ["OBS-01", "OBS-02", "OBS-03", "OBS-04"],
        "类型": ["塔吊", "烟囱", "建筑", "山体"],
        "高度(ft)": [500, 480, 200, 1200],
        "穿越限面": ["OAS超限", "安全", "安全", "起飞面超限"],
        "权重影响": ["🔴 危险", "🟢 正常", "🟢 正常", "🔴 危险"]
    })
    
    def highlight_status(val):
        if '危险' in str(val): return 'color: #ff5252; font-weight: bold;'
        if '正常' in str(val): return 'color: #64ffda;'
        return ''
        
    st.dataframe(df_res.style.applymap(highlight_status, subset=['权重影响']), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    c1, c2 = st.columns([1,2])
    with c1:
        st.button("📦 导出 PEP 格式文档", type="primary", use_container_width=True)
    with c2:
        st.button("📊 导出 XLSX 分析报告", use_container_width=True)

