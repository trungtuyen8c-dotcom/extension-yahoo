#!/usr/bin/env bash
# SSH tunnel local -> VPS (mục 6). Thay VPS_USER/VPS_IP bằng giá trị thật;
# không phải root, xác minh host key trước khi dùng lần đầu.
set -euo pipefail

: "${VPS_USER:?Set VPS_USER, vd: export VPS_USER=deploy}"
: "${VPS_IP:?Set VPS_IP, vd: export VPS_IP=203.0.113.10}"
LOCAL_PORT="${LOCAL_PORT:-18000}"

exec ssh -N \
  -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:8000" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  "${VPS_USER}@${VPS_IP}"
