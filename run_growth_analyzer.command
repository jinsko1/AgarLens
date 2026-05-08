#!/bin/zsh
cd "$(dirname "$0")"
/usr/local/bin/python3 opencv_growth_ui.py 2>&1 | tee -a gui_startup.log
