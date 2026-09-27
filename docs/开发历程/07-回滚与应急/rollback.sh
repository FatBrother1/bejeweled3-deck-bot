#!/bin/bash
# BJBot 插件一键回滚：移出插件 + 重启 loader + 报告健康状态
export PATH=$PATH:/usr/bin:/bin
sudo -n rm -rf /home/deck/homebrew/plugins/BJBot
sudo -n systemctl restart plugin_loader
sleep 12
echo "插件数: $(ls /home/deck/homebrew/plugins/ | wc -l)  (基线 15)"
echo "BJBot : $(ls /home/deck/homebrew/plugins/ | grep -c BJBot)  (应为 0)"
echo "loader: $(sudo -n systemctl is-active plugin_loader)"
echo "内存  : $(free -m | awk "/Mem:/{print \$7}") MB 可用 / swap $(free -m | awk "/Swap:/{print \$3}") MB"
