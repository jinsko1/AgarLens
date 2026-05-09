#!/bin/zsh
cd "$(dirname "$0")"
echo "\n--- Launch $(date) ---" >> gui_startup.log
/usr/local/bin/python3 "$PWD/growth_analyzer_gui.py" >> gui_startup.log 2>&1
