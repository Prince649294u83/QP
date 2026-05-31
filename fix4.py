import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix the syntax errors
content = content.replace('\\Generation failed to start: {', '`Generation failed to start: ${')
content = content.replace('}\\,\n    );', '}`,\n    );')
content = content.replace('\\`', '`') # fix any stray backticks that were converted to \\` by powershell if any?
# Wait, powershell converts `G to G. Let's see what is in the file.
# We can just replace the whole toast.error block

block_to_replace = '''    toast.error(
      \Generation failed to start: {
        (createGenerationJobMutation.error as Error).message || "Unknown error"
      }\,
    );'''

correct_block = '''    toast.error(
      `Generation failed to start: ${
        (createGenerationJobMutation.error as Error).message || "Unknown error"
      }`,
    );'''

content = content.replace(block_to_replace, correct_block)

# Fix statusKey
status_key_wrong = '''    const statusKey = \`{generationJob.id}:{generationJob.status}\`;'''
status_key_wrong2 = '''    const statusKey = {generationJob.id}:{generationJob.status};'''
status_key_correct = '''    const statusKey = `${generationJob.id}:${generationJob.status}`;'''

# Let's just use regex to fix it
content = re.sub(r'const statusKey = [^\n]+', status_key_correct, content)

# 2. Remove RBT Levels FormField
start_str = '<FormField\n                      control={form.control}\n                      name="rbtLevels"'
# Let's find the exact block for RBT levels using regex or simple search.
# We know it starts with <FormField control={form.control} name="rbtLevels"
start_idx = content.find('name="rbtLevels"')
if start_idx != -1:
    tag_start = content.rfind('<FormField', 0, start_idx)
    
    # We need to find the matching </FormField>
    # Since there is a nested FormField, we can just find the end of this block by searching for the next <FormField or </form> or <Separator />
    
    end_str = '</FormItem>\n                      )}\n                    />'
    end_idx = content.find(end_str, tag_start)
    if end_idx != -1:
        # Also remove the <Separator /> before it
        sep_idx = content.rfind('<Separator />', 0, tag_start)
        if sep_idx != -1 and sep_idx > tag_start - 200:
            tag_start = sep_idx
            
        content = content[:tag_start] + content[end_idx + len(end_str):]
        print('Removed RBT Levels Field')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done fixing!')
