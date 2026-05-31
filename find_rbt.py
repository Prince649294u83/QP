import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Let's see if we can find RBT Levels Field
rbt_idx = content.find('name="rbtLevels"')
if rbt_idx != -1:
    print('Found rbtLevels at index', rbt_idx)
    start_rbt = content.rfind('<FormField', 0, rbt_idx)
    end_rbt = content.find('/>\n', rbt_idx)
    if end_rbt != -1:
        end_rbt = content.find('/>', end_rbt) + 2
    # maybe it spans multiple lines up to </FormField>
    end_rbt = content.find('</FormField>', rbt_idx) + len('</FormField>')
    print(content[start_rbt:end_rbt])
