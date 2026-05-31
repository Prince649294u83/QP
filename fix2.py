import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove rbtLevels from step1Schema
content = content.replace(
'''  teachingDept: z.string().min(1, "Required"),
  examType: z.string().min(1, "Required"),
  rbtLevels: z.array(z.string()).min(1, "Select at least one RBT level")
});''',
'''  teachingDept: z.string().min(1, "Required"),
  examType: z.string().min(1, "Required"),
});''')

# 2. Remove rbtLevels from form defaultValues and watch
content = content.replace(
'''    defaultValues: {
      maxMarks: 50,
      rbtLevels: ["L1", "L2", "L3"],
      duration: "1.5 hrs"
    }''',
'''    defaultValues: {
      maxMarks: 50,
      duration: "1.5 hrs"
    }''')

content = content.replace(
'''  const selectedSubjectId = form.watch("subjectId");
  const selectedMaxMarks = form.watch("maxMarks") || 50;
  const selectedRbtLevels = form.watch("rbtLevels");''',
'''  const selectedSubjectId = form.watch("subjectId");
  const selectedMaxMarks = form.watch("maxMarks") || 50;''')

# 3. Remove selectedRbtLevels from manualQuestionResults
content = content.replace(
'''      if (selectedModules.length > 0 && !selectedModules.includes(question.module_number)) {
        return false;
      }
      if (selectedRbtLevels.length > 0 && !selectedRbtLevels.includes(question.bloom_level)) {
        return false;
      }
      if (!searchTerm) {''',
'''      if (selectedModules.length > 0 && !selectedModules.includes(question.module_number)) {
        return false;
      }
      if (!searchTerm) {''')

content = content.replace(
''', [deferredManualSearch, selectedModules, selectedRbtLevels, subjectQuestions]);''',
''', [deferredManualSearch, selectedModules, subjectQuestions]);''')

# 4. Remove rbtLevels from generateQuestions() payload
content = content.replace(
'''      prompt: `Generate ${values.examType} paper for ${subject?.name} covering modules ${selectedModules.join(", ")} with RBT levels ${values.rbtLevels.join(", ")} and CO targets ${Object.entries(coTargets).map(([co, value]) => `${co}:${value}%`).join(", ")}`,
      rbt_levels: values.rbtLevels,''',
'''      prompt: `Generate ${values.examType} paper for ${subject?.name} covering modules ${selectedModules.join(", ")} and CO targets ${Object.entries(coTargets).map(([co, value]) => `${co}:${value}%`).join(", ")}`,''')


# 5. difficultyDist hook update
content = content.replace(
'''  const [manualSelectedIds, setManualSelectedIds] = useState<number[]>([]);
  const [difficultyDist, setDifficultyDist] = useState({ easy: 30, medium: 50, hard: 20 });
  const [selectedModules, setSelectedModules] = useState<number[]>([1, 2, 3, 4, 5]);''',
'''  const [manualSelectedIds, setManualSelectedIds] = useState<number[]>([]);
  const [selectedModules, setSelectedModules] = useState<number[]>([1, 2, 3, 4, 5]);''')

content = content.replace(
'''  const [moduleCoMapping, setModuleCoMapping] = useState<Record<number, string[]>>({
    1: ["CO1"],
    2: ["CO2"],
    3: ["CO3"],
    4: ["CO4"],
    5: ["CO5"],
  });''',
'''  const [moduleCoMapping, setModuleCoMapping] = useState<Record<number, string[]>>({
    1: ["CO1"],
    2: ["CO2"],
    3: ["CO3"],
    4: ["CO4"],
    5: ["CO5"],
  });

  const difficultyDist = useMemo(() => {
    const totalSelected = selectedModules.length;
    if (totalSelected === 0) return { easy: 0, medium: 0, hard: 0 };
    
    let easyModules = 0;
    let mediumModules = 0;
    let hardModules = 0;

    selectedModules.forEach(m => {
      const cos = moduleCoMapping[m] || [];
      if (cos.includes("CO1")) {
        easyModules++;
      } else if (cos.includes("CO2") || cos.includes("CO3")) {
        mediumModules++;
      } else if (cos.includes("CO4") || cos.includes("CO5") || cos.includes("CO6")) {
        hardModules++;
      } else {
        mediumModules++;
      }
    });

    const totalValid = easyModules + mediumModules + hardModules;
    if (totalValid === 0) return { easy: 0, medium: 0, hard: 0 };

    return {
      easy: Math.round((easyModules / totalValid) * 100),
      medium: Math.round((mediumModules / totalValid) * 100),
      hard: Math.round((hardModules / totalValid) * 100)
    };
  }, [selectedModules, moduleCoMapping]);''')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Replaced parts 1-5')
