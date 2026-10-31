#!/bin/sh
# SKV: MCP :8765 is reachable only from localhost and docker bridges (nginx-proxy); everyone else gets a TCP reset.
# Idempotent; run by skv-mcp-firewall.service at boot.
set -e
IPT=/usr/sbin/iptables
CH=SKV_MCP_8765
$IPT -N $CH 2>/dev/null || $IPT -F $CH
$IPT -A $CH -i lo -j RETURN
$IPT -A $CH -s 172.16.0.0/12 -j RETURN
$IPT -A $CH -p tcp -j REJECT --reject-with tcp-reset
while $IPT -C INPUT -p tcp --dport 8765 -j $CH 2>/dev/null; do $IPT -D INPUT -p tcp --dport 8765 -j $CH; done
$IPT -I INPUT 1 -p tcp --dport 8765 -j $CH
# IPv6: MCP binds IPv4 only, but block it too in case the bind changes
if command -v ip6tables >/dev/null; then
  ip6tables -C INPUT -p tcp --dport 8765 ! -i lo -j REJECT --reject-with tcp-reset 2>/dev/null || ip6tables -I INPUT 1 -p tcp --dport 8765 ! -i lo -j REJECT --reject-with tcp-reset
fi
