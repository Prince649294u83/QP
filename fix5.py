import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix haystack line
bad_str = r'\${$}{question.text} {question.course_outcome} {question.bloom_level} {question.difficulty}\.toLowerCase()'
# Actually, the error says:
# const haystack = \${"$"}{question.text} {question.course_outcome} {question.bloom_level} {question.difficulty}\...
# Let's just use regex to replace the entire line for `haystack`
pattern = r'const haystack = [^\n]+'
correct_line = 'const haystack = `${question.text} ${question.course_outcome} ${question.bloom_level} ${question.difficulty}`.toLowerCase();'

content = re.sub(pattern, correct_line, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed haystack!')
