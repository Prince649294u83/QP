import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

rbt_start = content.find('<FormField\\n                        control={form.control}\\n                        name="rbtLevels"')
if rbt_start == -1:
    rbt_start = content.find('name="rbtLevels"')

if rbt_start != -1:
    print('Found rbtLevels at', rbt_start)
    # Find start of FormField
    start_tag = content.rfind('<FormField', 0, rbt_start)
    # This is tricky because it has nested FormFields for the mapping over levels!
    # Instead, let's use a regex to match the exact block:
    # <FormField control={form.control} name="rbtLevels" render={...} />
    # Let's print out what is there
    print(content[start_tag-100:start_tag+500])
