#!/bin/bash
#
# Opens multiple files in TextMate.  These are the files I'll usually edit
# in a rapid cycle.
#

projDir="$HOME/git/pithy"
files="static/lame.css templates/form.html rubustat_daemon.py rubustat_web_interface.py"

cd  "$projDir"

echo "Opening files:"
for i in "$files"; do
  echo "    $i"
done

m --no-wait $files 
