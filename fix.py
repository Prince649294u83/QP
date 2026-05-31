import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

marker1 = 'toast.success("Paper downloaded successfully!");'
marker2 = '    (createGenerationJobMutation.isPending'

start_idx = content.find(marker1)
end_idx = content.find(marker2)

if start_idx != -1 and end_idx != -1:
    print('Found both markers, doing replacement!')
    
    missing_code = '''
    } catch (err) {
      toast.error("Download failed");
    }
  };

  useEffect(() => {
    if (!createGenerationJobMutation.data?.id) {
      return;
    }

    if (activeJobId === createGenerationJobMutation.data.id) {
      return;
    }

    setActiveJobId(createGenerationJobMutation.data.id);
    setLastHandledJobState(null);
    setCurrentStep(3);
    toast.success("Generation queued. Preview will update automatically.");
  }, [activeJobId, createGenerationJobMutation.data]);

  useEffect(() => {
    if (!createGenerationJobMutation.isError) {
      return;
    }

    toast.error(
      \Generation failed to start: {
        (createGenerationJobMutation.error as Error).message || "Unknown error"
      }\,
    );
  }, [createGenerationJobMutation.error, createGenerationJobMutation.isError]);

  useEffect(() => {
    if (!generationJob) {
      return;
    }

    const statusKey = \${"$"}{generationJob.id}:{generationJob.status}\;
    if (statusKey === lastHandledJobState) {
      return;
    }

    if (generationJob.status === "completed" && generationJob.paper) {
      setGeneratedPaper(generationJob.paper);
      setGeneratedQuestions(generationJob.paper.questions || []);
      setCurrentStep(3);
      setLastHandledJobState(statusKey);
      toast.success("Question paper generated successfully!");
      return;
    }

    if (generationJob.status === "failed") {
      setLastHandledJobState(statusKey);
      toast.error(generationJob.error_message || "Question paper generation failed");
    }
  }, [generationJob, lastHandledJobState]);

  const form = useForm<z.infer<typeof step1Schema>>({
    resolver: zodResolver(step1Schema),
    defaultValues: {
      maxMarks: 50,
      duration: "1.5 hrs"
    }
  });
  const selectedSubjectId = form.watch("subjectId");
  const selectedMaxMarks = form.watch("maxMarks") || 50;
  const deferredManualSearch = useDeferredValue(manualSearch);
  const selectedSubject = subjectsData.find(
    (subject) => subject.id.toString() === selectedSubjectId,
  );
  const departmentOptions = useMemo(
    () =>
      Array.from(
        new Set(
          subjectsData
            .map((subject) => subject.department_name)
            .filter((value): value is string => Boolean(value)),
        ),
      ),
    [subjectsData],
  );
  const blueprint = useMemo(
    () => buildQuestionBlueprint(selectedMaxMarks),
    [selectedMaxMarks],
  );
  const requiredQuestionCount = blueprint.length;
  const { data: bankSummary } = useQuestionBankSummary(
    selectedSubjectId ? parseInt(selectedSubjectId) : undefined,
  );
  const { data: subjectQuestions = [], isLoading: isLoadingManualQuestions } = useQuestions(
    selectedSubjectId ? parseInt(selectedSubjectId) : undefined,
  );

  useEffect(() => {
    if (!selectedSubject) {
      return;
    }

    form.setValue("department", selectedSubject.department_name || "");
    form.setValue("semester", selectedSubject.semester.toString());
    if (!form.getValues("teachingDept")) {
      form.setValue("teachingDept", selectedSubject.department_name || "AIML");
    }
  }, [form, selectedSubject]);

  useEffect(() => {
    setManualSelectedIds([]);
    setManualSearch("");
  }, [selectedSubjectId, selectedMaxMarks]);

  const manualQuestionResults = useMemo(() => {
    const searchTerm = deferredManualSearch.trim().toLowerCase();
    return subjectQuestions.filter((question) => {
      if (selectedModules.length > 0 && !selectedModules.includes(question.module_number)) {
        return false;
      }
      if (!searchTerm) {
        return true;
      }
      const haystack = \${"$"}{question.text} {question.course_outcome} {question.bloom_level} {question.difficulty}\.toLowerCase();
      return haystack.includes(searchTerm);
    });
  }, [deferredManualSearch, selectedModules, subjectQuestions]);
  const visibleManualQuestionResults = useMemo(
    () => manualQuestionResults.slice(0, 200),
    [manualQuestionResults],
  );
  const isGenerating =
    createGenerationJobMutation.isPending ||
    generationJob?.status === "pending" ||
    generationJob?.status === "processing";
  const generationProgress = generationJob?.progress ?? (createGenerationJobMutation.isPending ? 5 : 0);
  const generationStageMessage =
    generationJob?.message ||
'''
    new_content = content[:start_idx + len(marker1)] + '\n' + missing_code + content[end_idx:]
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Done replacing.')
else:
    print('Could not find markers!')
    print(start_idx, end_idx)
