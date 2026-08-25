#!/data/data/com.termux/files/usr/bin/bash

LOG_FILE="/storage/emulated/0/Download/key_history.txt"

echo "Бақылау басталды! Тоқтату үшін CTRL+C басыңыз."
echo "=== ЖАЗБА БАСТАЛДЫ: $(date) ===" > $LOG_FILE

getevent -l | while read line; do
    echo "$(date +%H:%M:%S) - $line" >> $LOG_FILE
done
