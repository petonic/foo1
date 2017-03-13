#!/bin/bash
#
# Opens multiple files in TextMate.  These are the files I'll usually edit
# in a rapid cycle.
#

projDir="$HOME/git/pithy"
files="websrvd.py thermod.py config.txt static/lame.css templates/form.html"

cd  "$projDir"

echo "Opening files:"
for i in "$files"; do
  echo "    $i"
done

mate --no-wait $files
