#!/usr/bin/env bash
# 下载 Gutenberg 公版书作为 haystack 语料（约 5.7MB）
set -e
mkdir -p corpus
cd corpus
for b in "1342 pride_and_prejudice" "2701 moby_dick" "1661 sherlock_holmes" \
         "84 frankenstein" "74 tom_sawyer" "1260 jane_eyre" "1400 great_expectations"; do
  set -- $b
  [ -s "$2.txt" ] || curl -sS -o "$2.txt" "https://www.gutenberg.org/cache/epub/$1/pg$1.txt" &
done
wait
# 让 serve.py 重新合并 corpus_all.txt
rm -f ../corpus_all.txt
ls -la && echo "OK: $(cat *.txt | wc -c) bytes"
