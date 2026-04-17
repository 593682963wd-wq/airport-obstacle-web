#!/bin/bash
# ═══════════════════════════════════════════════════════════
# 🖥 机场障碍物分析系统 — 本地启动脚本（备用方案）
# ═══════════════════════════════════════════════════════════
# 当云端部署尚未完成时，可用此脚本在本机启动
# 同一 WiFi 下的同事可通过「局域网地址」访问
#
# 使用方法：双击此文件 或 在终端运行：
#   cd ~/Desktop/airport-obstacle-web && bash 本地启动.sh
# ═══════════════════════════════════════════════════════════

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export PATH="$HOME/Library/Python/3.13/bin:$PATH"

BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ✈  机场障碍物分析系统 — 本地启动${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# 检查 streamlit
if ! command -v streamlit &>/dev/null; then
    echo -e "${YELLOW}📦 正在安装依赖...${NC}"
    pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt 2>&1 | tail -3
fi

# 获取本机IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "无法获取")

echo -e "${GREEN}🚀 正在启动分析系统...${NC}"
echo ""
echo -e "  ${BLUE}本机访问:${NC}    ${GREEN}http://localhost:8501${NC}"
echo -e "  ${BLUE}局域网访问:${NC}  ${GREEN}http://${LOCAL_IP}:8501${NC}"
echo ""
echo -e "${YELLOW}💡 同一 WiFi 下的同事可以用「局域网访问」地址打开${NC}"
echo -e "${YELLOW}💡 按 Ctrl+C 停止服务${NC}"
echo ""

streamlit run app.py \
    --server.headless true \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --browser.gatherUsageStats false
