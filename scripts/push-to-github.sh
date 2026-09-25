#!/bin/bash
# 一键推送到 GitHub
#
# 用法（三选一）：
#   GITHUB_TOKEN=ghp_xxx bash push-to-github.sh <用户名> [仓库名]
#   bash push-to-github.sh <用户名> <仓库名>          # 会用 git credential 里的凭据
#   bash push-to-github.sh --local-only               # 只 commit，不推
#
# 例：
#   GITHUB_TOKEN=ghp_abc123 bash push-to-github.sh myname bejeweled3-deck-bot
set -e

USER="${1}"
REPO="${2:-bejeweled3-deck-bot}"
VISIBILITY="${VISIBILITY:-public}"

if [ "$USER" = "--local-only" ]; then
  echo "只做本地提交。"
  exit 0
fi

if [ -z "$USER" ] || [ "$USER" = "--help" ]; then
  sed -n '2,14p' "$0"
  exit 0
fi

TOKEN="${GITHUB_TOKEN:-}"
AUTH_URL="https://github.com/${USER}/${REPO}.git"
if [ -n "$TOKEN" ]; then
  PUSH_URL="https://${USER}:${TOKEN}@github.com/${USER}/${REPO}.git"
else
  PUSH_URL="$AUTH_URL"
  echo "⚠️  未提供 GITHUB_TOKEN，将使用系统 git 凭据（可能失败）"
fi

echo "════ 1/5 创建远端仓库 ════"
if [ -n "$TOKEN" ]; then
  RESP=$(curl -s -o /tmp/gh_create.json -w "%{http_code}" \
    -X POST https://api.github.com/user/repos \
    -H "Authorization: token ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -d "{\"name\":\"${REPO}\",\"description\":\"Bejeweled 3 auto-play bot for Steam Deck. Reads the board from game memory (read-only, never writes), plays with a simulated mouse. + Decky plugin for Game Mode. 100% AI-developed.\",\"private\":$([ "$VISIBILITY" = "private" ] && echo true || echo false),\"has_issues\":true,\"has_wiki\":false}")
  if [ "$RESP" = "201" ]; then
    echo "   ✅ 仓库已创建"
  elif [ "$RESP" = "422" ]; then
    echo "   ℹ️  仓库已存在，继续（422）"
  else
    echo "   ⚠️  HTTP $RESP"; head -c 400 /tmp/gh_create.json; echo
  fi
else
  echo "   跳过（无 token）"
fi

echo "════ 2/5 设置 remote ════"
git remote remove origin 2>/dev/null || true
git remote add origin "$AUTH_URL"
echo "   origin → $AUTH_URL"

echo "════ 3/4 填充 README 里的用户名占位符 ════"
# README 里写的是 <你的用户名>，换成实际用户名让链接可用
if grep -q '<你的用户名>' README.md 2>/dev/null; then
  sed -i "s|<你的用户名>|${USER}|g" README.md
  echo "   ✅ README.md 里的占位符已替换为 ${USER}"
  git add README.md
  git -c user.name="AI (deepseek-v4.1-flash)" -c user.email="ai@deepseek.local" \
      commit -q -m "docs: 填充仓库用户名" || true
else
  echo "   无需替换"
fi

echo "════ 4/4 设置提交者 ════"
git config user.name "AI (deepseek-v4.1-flash)"
git config user.email "ai@deepseek.local"
echo "   AI (deepseek-v4.1-flash) <ai@deepseek.local>"

echo "════ 5/5 推送 ════"
git branch -M main
if [ -n "$TOKEN" ]; then
  git push -q "https://${USER}:${TOKEN}@github.com/${USER}/${REPO}.git" main --force
else
  git push -u origin main
fi
echo "   ✅ 推送完成"
echo
echo "════ 仓库地址 ════"
echo "   https://github.com/${USER}/${REPO}"
