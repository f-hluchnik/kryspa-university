---
title: "Absurdní program"
date: 2026-10-29
---

## Větorozkladoskládač
Tento program dokáže rozložit větu na slova a zase ji složit.
```python
word_list = []
sentence = 'Tato věta bude rozložena a zase složena.'
for word in sentence:
    word_list.append(word)

new_sentence = ''
for word in word_list:
    new_sentence += word

print(new_sentence)
```
