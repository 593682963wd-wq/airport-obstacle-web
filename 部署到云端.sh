#!/bin/bash
# ═══════════════════════════════════════════════════════════
# 🚀 机场障碍物分析系统 — 一键云端部署脚本
# ═══════════════════════════════════════════════════════════
# 运行本脚本后，系统将自动完成以下操作：
# 1. 登录 GitHub（需在浏览器确认）
# 2. 创建 GitHub 仓库并推送代码
# 3. 告诉你如何在 Streamlit Cloud 上免费部署
# 4. 部署完成后，任何人随时都可以访问网址使用
#
# 使用方法：打开终端，运行：
#   cd ~/Desktop/airport-obstacle-web && bash 部署到云端.sh
# ═══════════════════════════════════════════════════════════

set -e

BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

GH="/tmp/gh_extract/gh_2.62.0_macOS_arm64/bin/gh"
REPO_NAME="airport-obstacle-web"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  🚀 机场障碍物分析系统 — 一键云端部署${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── 第1步：检查 gh CLI ──
if [ ! -x "$GH" ]; then
    echo -e "${YELLOW}📦 正在下载 GitHub CLI ...${NC}"
    cd /tmp
    curl -sL "https://github.com/cli/cli/releases/download/v2.62.0/gh_2.62.0_macOS_arm64.zip" -o gh.zip
    unzip -o gh.zip -d gh_extract >/dev/null 2>&1
    chmod +x "$GH"
    cd "$DIR"
    echo -e "${GREEN}✅ GitHub CLI 已准备就绪${NC}"
fi

# ── 第2步：登录 GitHub ──
echo ""
echo -e "${BLUE}━━━ 第1步：登录 GitHub ━━━${NC}"
if ! "$GH" auth status >/dev/null 2>&1; then
    echo -e "${YELLOW}🔐 即将打开浏览器进行 GitHub 登录...${NC}"
    echo -e "${YELLOW}   请在浏览器中确认授权${NC}"
    echo ""
    "$GH" auth login --hostname github.com --git-protocol https --web
    echo -e "${GREEN}✅ GitHub 登录成功！${NC}"
else
    echo -e "${GREEN}✅ 已登录 GitHub${NC}"
fi

# ── 第3步：创建仓库 ──
echo ""
echo -e "${BLUE}━━━ 第2步：创建 GitHub 仓库 ━━━${NC}"

# 检查仓库是否已存在
if "$GH" repo view "593682963wd-wq/$REPO_NAME" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ 仓库已存在，跳过创建${NC}"
else
    echo -e "${YELLOW}📁 正在创建仓库 $REPO_NAME ...${NC}"
    "$GH" repo create "$REPO_NAME" --public --description "✈ 机场障碍物对飞行影响分析系统 Web版 · ICAO Annex 14" --source . --push
    echo -e "${GREEN}✅ 仓库创建完成！${NC}"
fi

# ── 第4步：推送代码 ──
echo ""
echo -e "${BLUE}━━━ 第3步：推送代码 ━━━${NC}"

# 确保 remote 设置正确
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/593682963wd-wq/$REPO_NAME.git"
git push -u origin main 2>&1 || {
    echo -e "${YELLOW}首次推送需要认证，使用 gh 进行认证推送...${NC}"
    "$GH" repo sync --source . 2>&1 || git push -u origin main 2>&1
}
echo -e "${GREEN}✅ 代码推送完成！${NC}"

# ── 第5步：部署指南 ──
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🎉 代码已上传至 GitHub！${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}📌 现在完成最后一步（只需做一次，5分钟）：${NC}"
echo ""
echo -e "  ${BLUE}1.${NC} 打开浏览器访问: ${GREEN}https://share.streamlit.io${NC}"
echo -e "  ${BLUE}2.${NC} 点击 ${GREEN}「Continue with GitHub」${NC} 用 GitHub 账号登录"
echo -e "  ${BLUE}3.${NC} 点击 ${GREEN}「New app」${NC}"
echo -e "  ${BLUE}4.${NC} 选择仓库: ${GREEN}593682963wd-wq/$REPO_NAME${NC}"
echo -e "  ${BLUE}5.${NC} Branch: ${GREEN}main${NC}"
echo -e "  ${BLUE}6.${NC} Main file path: ${GREEN}app.py${NC}"
echo -e "  ${BLUE}7.${NC} App URL 自定义为: ${GREEN}wangdi-obstacle${NC}"
echo -e "     (最终网址: ${GREEN}https://wangdi-obstacle.streamlit.app${NC})"
echo -e "  ${BLUE}8.${NC} 点击 ${GREEN}「Deploy!」${NC}"
echo ""
echo -e "${GREEN}  部署完成后，任何人都可以通过以下网址访问：${NC}"
echo -e "${GREEN}  👉 https://wangdi-obstacle.streamlit.app${NC}"
echo -e "${GREEN}  即使你关机，别人也能正常使用！${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}💡 提示：Streamlit Cloud 完全免费，自动运行，不需要你的电脑开机${NC}"
echo ""
