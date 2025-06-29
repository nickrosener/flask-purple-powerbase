#!/bin/bash

while inotifywait -e modify,close_write,move_self,attrib /home/nick/Development/flask-purple-powerbase/app.py; do
  echo "Detected app.py change"
  sudo systemctl restart nurple.service
done