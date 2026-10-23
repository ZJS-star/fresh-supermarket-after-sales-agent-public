#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print '请先按 agent_mvp/demo/README.md 使用 Python 3.11+ 创建 .venv 并安装 requirements.txt。'
  exit 1
fi
.venv/bin/python -m agent_mvp.demo.prepare
if [[ "${1:-}" == '--software' ]]; then
  print '软件交互测试模式：顾客 http://127.0.0.1:8001/  商家 /staff  控制台 /console'
  exec .venv/bin/python -m uvicorn agent_mvp.demo.software:app --host 127.0.0.1 --port "${PORT:-8001}" --no-access-log
fi
print '实时演示：顾客 http://127.0.0.1:8000/  商家 /staff  控制台 /console'
exec .venv/bin/python -m uvicorn agent_mvp.api:app --host 127.0.0.1 --port "${PORT:-8000}" --no-access-log
