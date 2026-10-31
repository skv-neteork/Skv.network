#!/bin/bash
# copy installer files to the served dir (container mounts only src/app)
set -e; D=/root/skv-core/src/app/downloads/installer; mkdir -p $D
cp /root/skv-core/installer/{install.sh,install.ps1,skv_hook.py,skv_config.py} $D/
