import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowDown, ArrowUp, Check, ChevronRight, Download, Edit, FileText, RotateCw, Search, Settings2, X, ShieldCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { EditablePaperPreview } from "@/components/editable-paper-preview";
import { useSubjectsApiV1SubjectsGet } from "@workspace/api-client-react";
import {
  type GeneratedPaper,
  useCreatePaperGenerationJob,
  usePaperGenerationJob,
  useQuestionBankSummary,
  useQuestions,
  useUpdatePaper,
} from "@/lib/ai-api";
import { exportToDocx } from "@/utils/docxExport";

const step1Schema = z.object({
  department: z.string().min(1, "Required"),
  subjectId: z.string().min(1, "Required"),
  semester: z.string().min(1, "Required"),
  batch: z.string().min(1, "Required"),
  maxMarks: z.coerce.number().min(1, "Required").default(50),
  duration: z.string().min(1, "Required"),
  dateOfIat: z.string().min(1, "Required"),
  teachingDept: z.string().min(1, "Required"),
  examType: z.string().min(1, "Required"),
});

const steps = [
  { id: 1, name: "Configuration", icon: Settings2 },
  { id: 2, name: "Strategy", icon: FileText },
  { id: 3, name: "Preview", icon: Check }
];

function buildQuestionBlueprint(maxMarks: number) {
  if (maxMarks <= 50) {
    const patterns = [
      ...Array.from({ length: 4 }, () => [5, 5] as const),
      ...Array.from({ length: 6 }, () => [4, 6] as const),
    ];
    return patterns.flatMap(([partA, partB], index) => [
      {
        questionNumber: index + 1,
        subpart: "a",
        label: `${index + 1}a`,
        marks: partA,
        moduleNumber: Math.floor(index / 2) + 1,
      },
      {
        questionNumber: index + 1,
        subpart: "b",
        label: `${index + 1}b`,
        marks: partB,
        moduleNumber: Math.floor(index / 2) + 1,
      },
    ]);
  }

  return [
    ...[
      [1, "a", 6, 1],
      [1, "b", 6, 1],
      [1, "c", 8, 1],
      [2, "a", 6, 1],
      [2, "b", 6, 1],
      [2, "c", 8, 1],
      [3, "a", 5, 2],
      [3, "b", 8, 2],
      [3, "c", 7, 2],
      [4, "a", 5, 2],
      [4, "b", 8, 2],
      [4, "c", 7, 2],
      [5, "a", 5, 3],
      [5, "b", 8, 3],
      [5, "c", 7, 3],
      [6, "a", 5, 3],
      [6, "b", 8, 3],
      [6, "c", 7, 3],
      [7, "a", 10, 4],
      [7, "b", 10, 4],
      [8, "a", 10, 4],
      [8, "b", 10, 4],
      [9, "a", 10, 5],
      [9, "b", 10, 5],
      [10, "a", 10, 5],
      [10, "b", 10, 5],
    ] as const,
  ].map(([questionNumber, subpart, marks, moduleNumber]) => ({
    questionNumber,
    subpart,
    label: `${questionNumber}${subpart}`,
    marks,
    moduleNumber,
  }));
}

function normalizeQuestionForSimilarity(text: string) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function questionOverlapScore(left: string, right: string) {
  const leftTokens = new Set(normalizeQuestionForSimilarity(left).split(" ").filter((token) => token.length > 2));
  const rightTokens = new Set(normalizeQuestionForSimilarity(right).split(" ").filter((token) => token.length > 2));
  if (leftTokens.size === 0 || rightTokens.size === 0) {
    return 0;
  }

  const shared = [...leftTokens].filter((token) => rightTokens.has(token)).length;
  return shared / Math.max(Math.min(leftTokens.size, rightTokens.size), 1);
}

export default function GeneratePaper() {
  const [currentStep, setCurrentStep] = useState(1);
  const [isAutoGenerate, setIsAutoGenerate] = useState(true);
  const [generatedQuestions, setGeneratedQuestions] = useState<GeneratedPaper["questions"]>([]);
  const [generatedPaper, setGeneratedPaper] = useState<GeneratedPaper | null>(null);
  const [manualSearch, setManualSearch] = useState("");
  const [manualSelectedIds, setManualSelectedIds] = useState<number[]>([]);
  const [selectedModules, setSelectedModules] = useState<number[]>([1, 2, 3, 4, 5]);
  const [coTargets, setCoTargets] = useState<Record<string, number>>({
    "CO1": 20, "CO2": 20, "CO3": 20, "CO4": 20, "CO5": 20
  });
  const [moduleCoMapping, setModuleCoMapping] = useState<Record<number, string[]>>({
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
  }, [selectedModules, moduleCoMapping]);
  const [coDescriptions, setCoDescriptions] = useState<Record<string, string>>({
    CO1: "",
    CO2: "",
    CO3: "",
    CO4: "",
    CO5: "",
  });
  const [instructions, setInstructions] = useState("Instruction: Answer the following questions");
  const [useRag, setUseRag] = useState(true);
  const [semanticVariance, setSemanticVariance] = useState([50]);
  const [structuralVariance, setStructuralVariance] = useState([50]);
  const [contextVariance, setContextVariance] = useState([50]);
  const [difficultyVariance, setDifficultyVariance] = useState([50]);
  const [diagramVariance, setDiagramVariance] = useState([50]);
  const [useNotes, setUseNotes] = useState(true);
  const [useQuestionBank, setUseQuestionBank] = useState(true);
  const [usePreviousPapers, setUsePreviousPapers] = useState(false);
  const [useSyllabus, setUseSyllabus] = useState(true);
  const [strictSyllabus, setStrictSyllabus] = useState(true);
  const [activeJobId, setActiveJobId] = useState<number | undefined>();
  const [lastHandledJobState, setLastHandledJobState] = useState<string | null>(null);

  const { data: subjectsDataRaw = [] } = useSubjectsApiV1SubjectsGet();
  const subjectsData = subjectsDataRaw as any[];
  const createGenerationJobMutation = useCreatePaperGenerationJob();
  const updatePaperMutation = useUpdatePaper();
  const { data: generationJob } = usePaperGenerationJob(activeJobId);
  const traceabilityInsights = useMemo(() => {
    const highConfidence = generatedQuestions.filter((question) => (question.confidence ?? 0) >= 0.8).length;
    const lowConfidence = generatedQuestions.filter((question) => question.confidence != null && question.confidence < 0.5).length;
    const overlapWarnings = generatedQuestions.reduce((count, question, index) => {
      const hasOverlap = generatedQuestions.some((otherQuestion, otherIndex) => {
        if (index === otherIndex) {
          return false;
        }
        return questionOverlapScore(question.text || "", otherQuestion.text || "") >= 0.72;
      });
      return count + (hasOverlap ? 1 : 0);
    }, 0);
    const avgConfidence = generatedQuestions.length > 0
      ? generatedQuestions.reduce((sum, question) => sum + (question.confidence ?? 0.55), 0) / generatedQuestions.length
      : 0;
    const qualityScore = Math.max(
      0,
      Math.min(100, Math.round((avgConfidence * 72) + ((generatedQuestions.length - overlapWarnings) / Math.max(generatedQuestions.length, 1)) * 28)),
    );

    return {
      highConfidence,
      lowConfidence,
      overlapWarnings,
      qualityScore,
      sourceDocuments: new Set(generatedQuestions.flatMap((question) => question.source_documents || [])).size,
    };
  }, [generatedQuestions]);

  const handleDownload = async () => {
    const paperForDownload = generatedPaper
      ? { ...generatedPaper, questions: generatedQuestions }
      : null;

    if (!paperForDownload) {
      toast.error("No paper to download");
      return;
    }

    try {
      await exportToDocx(paperForDownload);
      toast.success("Paper downloaded successfully!");

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
      `Generation failed to start: ${
        (createGenerationJobMutation.error as Error).message || "Unknown error"
      }`,
    );
  }, [createGenerationJobMutation.error, createGenerationJobMutation.isError]);

  useEffect(() => {
    if (!generationJob) {
      return;
    }

        const statusKey = `${generationJob.id}:${generationJob.status}`;
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
      const haystack = `${question.text} ${question.course_outcome} ${question.bloom_level} ${question.difficulty}`.toLowerCase();
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
    (createGenerationJobMutation.isPending
      ? "Submitting the generation request"
      : "Preparing the next paper preview");

  const manualSelectedQuestions = useMemo(
    () =>
      manualSelectedIds
        .map((questionId) => subjectQuestions.find((question) => question.id === questionId))
        .filter((question): question is NonNullable<typeof question> => Boolean(question)),
    [manualSelectedIds, subjectQuestions],
  );

  const toggleManualQuestion = (questionId: number) => {
    setManualSelectedIds((current) => {
      if (current.includes(questionId)) {
        return current.filter((id) => id !== questionId);
      }
      if (current.length >= requiredQuestionCount) {
        toast.error(`This template needs exactly ${requiredQuestionCount} questions.`);
        return current;
      }
      return [...current, questionId];
    });
  };

  const moveManualQuestion = (index: number, direction: -1 | 1) => {
    setManualSelectedIds((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) {
        return current;
      }
      const reordered = [...current];
      [reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]];
      return reordered;
    });
  };

  const generateQuestions = () => {
    const values = form.getValues();
    if (selectedModules.length === 0) {
      toast.error("Select at least one module");
      return;
    }
    const unmappedModules = selectedModules.filter(
      (moduleNumber) => (moduleCoMapping[moduleNumber] || []).length === 0,
    );
    if (unmappedModules.length > 0) {
      toast.error(`Map COs for Module ${unmappedModules.join(", Module ")} before generating.`);
      return;
    }
    const durationMinutes = values.duration.includes('1.5') ? 90 : parseInt(values.duration) * 60 || 60;
    const subject = subjectsData.find(s => s.id.toString() === values.subjectId);
    const difficultyPreference = Object.entries(difficultyDist).sort((left, right) => right[1] - left[1]);
    const difficulty =
      difficultyPreference.length > 1 &&
      Math.abs(difficultyPreference[0][1] - difficultyPreference[1][1]) < 10
        ? "balanced"
        : difficultyPreference[0]?.[0] || "balanced";

    if (!isAutoGenerate && manualSelectedIds.length !== requiredQuestionCount) {
      toast.error(`Select exactly ${requiredQuestionCount} questions for this template.`);
      return;
    }

    createGenerationJobMutation.mutate({
      subject_id: parseInt(values.subjectId),
      title: `${values.examType} - ${subject?.name || 'Paper'}`,
      exam_type: values.examType,
      semester: values.semester,
      batch: values.batch,
      max_marks: values.maxMarks,
      duration_minutes: durationMinutes,
      exam_date: values.dateOfIat || undefined,
      teaching_department: values.teachingDept,
      prompt: `Generate ${values.examType} paper for ${subject?.name} covering modules ${selectedModules.join(", ")} and CO targets ${Object.entries(coTargets).map(([co, value]) => `${co}:${value}%`).join(", ")}`,
      module_numbers: selectedModules,
      co_targets: coTargets,
      module_co_mapping: moduleCoMapping,
      co_descriptions: coDescriptions,
      difficulty_distribution: difficultyDist,
      difficulty,
      instructions: instructions,
      manual_question_ids: isAutoGenerate ? undefined : manualSelectedIds,
      creativity: useRag ? 0.7 : 0.7,
      semantic_variance: useRag ? semanticVariance[0] / 100 : 0.5,
      structural_variance: useRag ? structuralVariance[0] / 100 : 0.5,
      context_variance: useRag ? contextVariance[0] / 100 : 0.5,
      difficulty_variance: useRag ? difficultyVariance[0] / 100 : 0.5,
      diagram_variance: useRag ? diagramVariance[0] / 100 : 0.5,
      use_notes: useRag ? useNotes : false,
      use_question_bank: useRag ? useQuestionBank : true,
      use_previous_papers: useRag ? usePreviousPapers : false,
      use_syllabus: useRag ? useSyllabus : true,
      strict_syllabus_mode: strictSyllabus,
    });
  };

  const handleQuestionsChange = (questions: GeneratedPaper["questions"]) => {
    setGeneratedQuestions(questions);

    if (!generatedPaper) {
      return;
    }

    const syncedPaper = { ...generatedPaper, questions };
    setGeneratedPaper(syncedPaper);

    updatePaperMutation.mutate(
      {
        paper_id: generatedPaper.id,
        question_updates: questions.map((question) => ({
          id: question.id,
          text: question.text,
          course_outcome: question.course_outcome || null,
          bloom_level: question.bloom_level || null,
          module_number: question.module_number || null,
          attached_images: question.attached_images || [],
        })),
      },
      {
        onSuccess: (updatedPaper) => {
          setGeneratedPaper(updatedPaper);
          setGeneratedQuestions(updatedPaper.questions || []);
        },
        onError: (error) => {
          toast.error(`Could not save paper edits: ${error.message}`);
        },
      },
    );
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold text-foreground font-serif tracking-tight">Generate Question Paper</h1>
        <p className="text-muted-foreground">Follow the steps to configure and generate an AI-powered question paper.</p>
      </div>

      {/* Progress Wizard */}
      <div className="relative">
        <div className="absolute top-1/2 left-0 w-full h-1 bg-muted -translate-y-1/2 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary"
            initial={{ width: "0%" }}
            animate={{ width: `${((currentStep - 1) / (steps.length - 1)) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
        <div className="relative flex justify-between">
          {steps.map((step) => {
            const isCompleted = currentStep > step.id;
            const isCurrent = currentStep === step.id;

            return (
              <div key={step.id} className="flex flex-col items-center gap-2">
                <div
                  className={`w-10 h-10 rounded-full flex items-center justify-center border-2 transition-colors duration-300 ${
                    isCompleted ? "bg-primary border-primary text-primary-foreground" :
                    isCurrent ? "bg-background border-primary text-primary" :
                    "bg-background border-muted text-muted-foreground"
                  }`}
                >
                  <step.icon className="h-5 w-5" />
                </div>
                <span className={`text-xs font-medium ${isCurrent || isCompleted ? "text-foreground" : "text-muted-foreground"}`}>
                  {step.name}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Form Area */}
      <Card className="border-muted shadow-sm overflow-hidden">
        <AnimatePresence mode="wait">
          {currentStep === 1 && (
            <motion.div
              key="step1"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
            >
              <Form {...form}>
                <form onSubmit={form.handleSubmit(() => setCurrentStep(2))}>
                  <CardHeader>
                    <CardTitle>Paper Configuration</CardTitle>
                    <CardDescription>Set up the basic details for the examination.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <FormField
                        control={form.control}
                        name="department"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Department</FormLabel>
                            <Select onValueChange={field.onChange} defaultValue={field.value}>
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Select department" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {departmentOptions.map((department) => (
                                  <SelectItem key={department} value={department}>
                                    {department}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="examType"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Exam Type</FormLabel>
                            <Select onValueChange={field.onChange} defaultValue={field.value}>
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Select exam type" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="IAT-1">First Internal Assessment (IAT-1)</SelectItem>
                                <SelectItem value="IAT-2">Second Internal Assessment (IAT-2)</SelectItem>
                                <SelectItem value="IAT-3">Third Internal Assessment (IAT-3)</SelectItem>
                                <SelectItem value="End-Sem">End Semester</SelectItem>
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="subjectId"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Subject</FormLabel>
                            <Select onValueChange={field.onChange} defaultValue={field.value}>
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Select subject" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {subjectsData.map(s => (
                                  <SelectItem key={s.id} value={s.id.toString()}>
                                    {s.name} ({s.code})
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <div className="grid grid-cols-2 gap-4">
                        <FormField
                          control={form.control}
                          name="semester"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Semester</FormLabel>
                              <Select onValueChange={field.onChange} defaultValue={field.value}>
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue placeholder="Select" />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  {[1,2,3,4,5,6,7,8].map(s => <SelectItem key={s} value={`${s}`}>{s}th</SelectItem>)}
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name="batch"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Batch</FormLabel>
                              <FormControl>
                                <Input placeholder="e.g. 2022-26" {...field} />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <FormField
                          control={form.control}
                          name="maxMarks"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Max Marks</FormLabel>
                              <Select onValueChange={(val) => field.onChange(parseInt(val))} defaultValue={field.value.toString()}>
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue placeholder="Select marks" />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  <SelectItem value="50">50 Marks</SelectItem>
                                  <SelectItem value="100">100 Marks</SelectItem>
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name="duration"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Duration</FormLabel>
                              <Select onValueChange={field.onChange} defaultValue={field.value}>
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue placeholder="Select" />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  <SelectItem value="1 hr">1 hr</SelectItem>
                                  <SelectItem value="1.5 hrs">1.5 hrs</SelectItem>
                                  <SelectItem value="2 hrs">2 hrs</SelectItem>
                                  <SelectItem value="3 hrs">3 hrs</SelectItem>
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </div>

                      <FormField
                        control={form.control}
                        name="dateOfIat"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Date of IAT</FormLabel>
                            <FormControl>
                              <Input type="date" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="teachingDept"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Teaching Department</FormLabel>
                            <FormControl>
                              <Input placeholder="e.g. AIML Dept" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    {selectedSubject && bankSummary && (
                      <div className="rounded-xl border bg-muted/20 p-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                          <div>
                            <p className="text-sm font-semibold">Question Bank Readiness</p>
                            <p className="text-sm text-muted-foreground">
                              {selectedSubject.name} currently has {bankSummary.total_questions} indexed questions across {bankSummary.total_documents} uploaded source files.
                            </p>
                          </div>
                          <div className="grid grid-cols-3 gap-3 text-center">
                            <div className="rounded-lg bg-background px-3 py-2">
                              <p className="text-lg font-bold">{bankSummary.retrieval_ready_questions}</p>
                              <p className="text-[11px] text-muted-foreground">Retrieval Ready</p>
                            </div>
                            <div className="rounded-lg bg-background px-3 py-2">
                              <p className="text-lg font-bold">{bankSummary.verified_questions}</p>
                              <p className="text-[11px] text-muted-foreground">Verified</p>
                            </div>
                            <div className="rounded-lg bg-background px-3 py-2">
                              <p className="text-lg font-bold">{bankSummary.pending_questions}</p>
                              <p className="text-[11px] text-muted-foreground">Pending</p>
                            </div>
                          </div>
                        </div>
                        {bankSummary.gaps.length > 0 && (
                          <p className="mt-3 text-xs text-amber-700">
                            Coverage watchlist: {bankSummary.gaps.slice(0, 2).join(" ")}
                          </p>
                        )}
                      </div>
                    )}

                    
                  </CardContent>
                  <CardFooter className="bg-muted/30 flex justify-end p-4 border-t">
                    <Button type="submit" className="px-8">
                      Next Step <ChevronRight className="ml-2 h-4 w-4" />
                    </Button>
                  </CardFooter>
                </form>
              </Form>
            </motion.div>
          )}

          {currentStep === 2 && (
            <motion.div
              key="step2"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
            >
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Question Selection Strategy</CardTitle>
                    <CardDescription>Configure how questions should be selected for the paper.</CardDescription>
                  </div>
                  <div className="flex items-center space-x-2 bg-muted p-2 rounded-lg">
                    <Label htmlFor="auto-mode" className={`text-sm cursor-pointer ${!isAutoGenerate ? 'font-bold' : ''}`}>Manual</Label>
                    <Switch
                      id="auto-mode"
                      checked={isAutoGenerate}
                      onCheckedChange={setIsAutoGenerate}
                    />
                    <Label htmlFor="auto-mode" className={`text-sm cursor-pointer ${isAutoGenerate ? 'font-bold text-primary' : ''}`}>AI Auto-Generate</Label>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-8">
                {isAutoGenerate ? (
                  <div className="space-y-8">
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                          <ShieldCheck className="h-4 w-4 text-primary" />
                          Academic Firewall: Module-CO Mapping
                        </h3>
                        <Badge variant="default" className="animate-pulse bg-primary/20 text-primary hover:bg-primary/30 border-primary/30">
                          FIREWALL ACTIVE
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">Select modules and strictly lock them to specific Course Outcomes. The generation engine will ONLY retrieve context matching this locked mapping.</p>

                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 rounded-lg border border-primary/20 bg-primary/5 p-4">
                        {[1, 2, 3, 4, 5].map((moduleNumber) => (
                          <div key={moduleNumber} className="space-y-3 rounded-md bg-background p-3 border shadow-sm">
                            <label className="flex items-center gap-3 text-sm font-semibold">
                              <Checkbox
                                checked={selectedModules.includes(moduleNumber)}
                                onCheckedChange={(checked) => {
                                  setSelectedModules((current) =>
                                    checked
                                      ? [...current, moduleNumber].sort((left, right) => left - right)
                                      : current.filter((value) => value !== moduleNumber),
                                  );
                                  // Auto-assign default CO based on module number if checking
                                  if (checked && !moduleCoMapping[moduleNumber]) {
                                    setModuleCoMapping(prev => ({
                                      ...prev,
                                      [moduleNumber]: [`CO${moduleNumber}`]
                                    }));
                                  } else if (!checked) {
                                    setModuleCoMapping(prev => {
                                      const newMapping = { ...prev };
                                      delete newMapping[moduleNumber];
                                      return newMapping;
                                    });
                                  }
                                }}
                              />
                              <span className={selectedModules.includes(moduleNumber) ? "text-primary" : "text-muted-foreground"}>Module {moduleNumber}</span>
                            </label>

                            {selectedModules.includes(moduleNumber) && (
                              <div className="pl-6 space-y-2">
                                <Label className="text-xs text-muted-foreground">Map to Course Outcome (Select ONE):</Label>
                                <div className="flex flex-wrap gap-2">
                                  {["CO1", "CO2", "CO3", "CO4", "CO5"].map(co => (
                                    <label key={co} className="flex items-center gap-1.5 text-xs">
                                      <Checkbox
                                        className="h-3.5 w-3.5"
                                        checked={(moduleCoMapping[moduleNumber] || []).includes(co)}
                                        onCheckedChange={(checked) => {
                                          setModuleCoMapping(prev => {
                                            const currentCOs = prev[moduleNumber] || [];
                                            const newCOs = checked
                                              ? [...currentCOs, co].sort()
                                              : currentCOs.filter(c => c !== co);
                                            return { ...prev, [moduleNumber]: newCOs };
                                          });
                                        }}
                                      />
                                      <span>{co}</span>
                                    </label>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Difficulty Distribution</h3>
                      <div className="space-y-6 bg-muted/20 p-6 rounded-lg border border-muted/50">
                        <div className="space-y-3">
                          <div className="flex justify-between items-center">
                            <Label>Easy (L1, L2)</Label>
                            <span className="text-sm font-medium">{difficultyDist.easy}%</span>
                          </div>
                          <Slider
                            value={[difficultyDist.easy]}
                            max={100}
                            step={5}
                            onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, easy: val[0] }))}
                          />
                        </div>
                        <div className="space-y-3">
                          <div className="flex justify-between items-center">
                            <Label>Medium (L3, L4)</Label>
                            <span className="text-sm font-medium">{difficultyDist.medium}%</span>
                          </div>
                          <Slider
                            value={[difficultyDist.medium]}
                            max={100}
                            step={5}
                            onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, medium: val[0] }))}
                          />
                        </div>
                        <div className="space-y-3">
                          <div className="flex justify-between items-center">
                            <Label>Hard (L5, L6)</Label>
                            <span className="text-sm font-medium">{difficultyDist.hard}%</span>
                          </div>
                          <Slider
                            value={[difficultyDist.hard]}
                            max={100}
                            step={5}
                            onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, hard: val[0] }))}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 text-green-500" />
                        Firewall Eligibility Status
                      </h3>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="p-4 border rounded-lg bg-green-500/5 border-green-500/20">
                          <h4 className="text-sm font-medium text-green-700 mb-2">Allowed Retrieval Zones</h4>
                          <ul className="text-sm space-y-1 text-muted-foreground">
                            {Object.entries(moduleCoMapping).map(([mod, cos]) => (
                              <li key={mod} className="flex items-center gap-2">
                                <Check className="h-3.5 w-3.5 text-green-600" />
                                Module {mod} → {cos.length > 0 ? cos.join(", ") : <span className="text-red-400 italic">No CO mapped</span>}
                              </li>
                            ))}
                            {Object.keys(moduleCoMapping).length === 0 && (
                              <li className="text-muted-foreground italic">Select modules to view eligible zones</li>
                            )}
                          </ul>
                        </div>

                        <div className="p-4 border rounded-lg bg-red-500/5 border-red-500/20">
                          <h4 className="text-sm font-medium text-red-700 mb-2">Blocked Globally</h4>
                          <ul className="text-sm space-y-1 text-muted-foreground">
                            {["CO1", "CO2", "CO3", "CO4", "CO5"].filter(co =>
                              !Object.values(moduleCoMapping).flat().includes(co)
                            ).map(co => (
                              <li key={co} className="flex items-center gap-2">
                                <X className="h-3.5 w-3.5 text-red-600" />
                                {co} Context Excluded
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">CO Descriptions for the Printed Paper</h3>
                      <div className="grid gap-4 md:grid-cols-2">
                        {["CO1", "CO2", "CO3", "CO4", "CO5"].map((co) => (
                          <div key={co} className="space-y-2">
                            <Label>{co}</Label>
                            <Textarea
                              value={coDescriptions[co]}
                              onChange={(event) =>
                                setCoDescriptions((current) => ({
                                  ...current,
                                  [co]: event.target.value,
                                }))
                              }
                              rows={2}
                              placeholder={`Description for ${co}`}
                            />
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <Label>Instruction Line</Label>
                      <Textarea
                        value={instructions}
                        onChange={(event) => setInstructions(event.target.value)}
                        rows={2}
                        placeholder="Instruction: Answer the following questions"
                      />
                    </div>

                    <Separator />

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h3 className="text-sm font-semibold uppercase tracking-wider text-primary">Knowledge Retrieval (RAG)</h3>
                          <p className="text-sm text-muted-foreground">Use AI to generate questions from uploaded academic documents</p>
                        </div>
                        <Switch checked={useRag} onCheckedChange={setUseRag} />
                      </div>

                      {useRag && (
                        <div className="rounded-lg border bg-muted/20 p-4 space-y-6">
                          <div className="space-y-4">
                            <Label className="text-base font-semibold">Variance Controls</Label>
                            <p className="text-xs text-muted-foreground">Fine-tune how the AI varies generated questions across different dimensions.</p>

                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <Label className="text-xs text-muted-foreground">Semantic Variance</Label>
                                <span className="text-xs font-medium">{semanticVariance[0]}%</span>
                              </div>
                              <Slider value={semanticVariance} max={100} step={5} onValueChange={setSemanticVariance} />
                            </div>

                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <Label className="text-xs text-muted-foreground">Structural Variance</Label>
                                <span className="text-xs font-medium">{structuralVariance[0]}%</span>
                              </div>
                              <Slider value={structuralVariance} max={100} step={5} onValueChange={setStructuralVariance} />
                            </div>

                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <Label className="text-xs text-muted-foreground">Context Variance</Label>
                                <span className="text-xs font-medium">{contextVariance[0]}%</span>
                              </div>
                              <Slider value={contextVariance} max={100} step={5} onValueChange={setContextVariance} />
                            </div>

                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <Label className="text-xs text-muted-foreground">Difficulty Variance</Label>
                                <span className="text-xs font-medium">{difficultyVariance[0]}%</span>
                              </div>
                              <Slider value={difficultyVariance} max={100} step={5} onValueChange={setDifficultyVariance} />
                            </div>

                            <div className="space-y-2">
                              <div className="flex justify-between items-center">
                                <Label className="text-xs text-muted-foreground">Diagram Variance</Label>
                                <span className="text-xs font-medium">{diagramVariance[0]}%</span>
                              </div>
                              <Slider value={diagramVariance} max={100} step={5} onValueChange={setDiagramVariance} />
                            </div>
                          </div>

                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="flex items-center space-x-2">
                              <Checkbox id="src-notes" checked={useNotes} onCheckedChange={(v) => setUseNotes(!!v)} />
                              <label htmlFor="src-notes" className="text-sm font-medium leading-none">Use Class Notes / Handouts</label>
                            </div>
                            <div className="flex items-center space-x-2">
                              <Checkbox id="src-qb" checked={useQuestionBank} onCheckedChange={(v) => setUseQuestionBank(!!v)} />
                              <label htmlFor="src-qb" className="text-sm font-medium leading-none">Use Verified Question Bank</label>
                            </div>
                            <div className="flex items-center space-x-2">
                              <Checkbox id="src-prev" checked={usePreviousPapers} onCheckedChange={(v) => setUsePreviousPapers(!!v)} />
                              <label htmlFor="src-prev" className="text-sm font-medium leading-none">Use Previous Papers</label>
                            </div>
                            <div className="flex items-center space-x-2">
                              <Checkbox id="src-syl" checked={useSyllabus} onCheckedChange={(v) => setUseSyllabus(!!v)} />
                              <label htmlFor="src-syl" className="text-sm font-medium leading-none">Enforce Syllabus Bounds</label>
                            </div>
                            <div className="flex items-center space-x-2 border-l pl-4 border-primary/20">
                              <Checkbox id="strict-syl" checked={strictSyllabus} onCheckedChange={(v) => setStrictSyllabus(!!v)} />
                              <label htmlFor="strict-syl" className="text-sm font-bold text-primary leading-none flex items-center gap-1.5">
                                <Sparkles className="h-3.5 w-3.5 text-primary animate-pulse" /> Strict Syllabus Firewall Mode
                              </label>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
                    <div className="space-y-4">
                      <div className="flex flex-col gap-2 rounded-lg border bg-muted/20 p-4">
                        <h3 className="text-lg font-medium">Manual Selection Mode</h3>
                        <p className="text-sm text-muted-foreground">
                          Select exactly {requiredQuestionCount} questions. Their order in the selected list becomes the final paper order and slot mapping.
                        </p>
                      </div>
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          value={manualSearch}
                          onChange={(event) => setManualSearch(event.target.value)}
                          placeholder="Search the selected subject question bank..."
                          className="pl-9"
                        />
                      </div>
                      {manualQuestionResults.length > visibleManualQuestionResults.length && (
                        <p className="text-xs text-muted-foreground">
                          Showing the first {visibleManualQuestionResults.length} matches to keep search responsive.
                        </p>
                      )}
                      <div className="max-h-[460px] overflow-y-auto rounded-lg border">
                        {isLoadingManualQuestions ? (
                          <div className="p-6 text-sm text-muted-foreground">
                            Loading question bank...
                          </div>
                        ) : manualQuestionResults.length === 0 ? (
                          <div className="p-6 text-sm text-muted-foreground">
                            No questions match the current subject, module, and RBT filters.
                          </div>
                        ) : (
                          <div className="divide-y">
                            {visibleManualQuestionResults.map((question) => {
                              const selectedIndex = manualSelectedIds.indexOf(question.id);
                              const isSelected = selectedIndex >= 0;
                              return (
                                <button
                                  key={question.id}
                                  type="button"
                                  onClick={() => toggleManualQuestion(question.id)}
                                  className={`w-full px-4 py-3 text-left transition-colors ${
                                    isSelected ? "bg-primary/5" : "hover:bg-muted/40"
                                  }`}
                                >
                                  <div className="flex items-start justify-between gap-4">
                                    <div className="space-y-2">
                                      <p className="text-sm font-medium leading-relaxed">
                                        {question.text}
                                      </p>
                                      <p className="text-xs text-muted-foreground">
                                        Module {question.module_number} • {question.course_outcome} • {question.bloom_level} • {question.difficulty} • {question.marks} marks
                                      </p>
                                    </div>
                                    <div className="shrink-0 text-xs font-medium">
                                      {isSelected ? `Slot ${blueprint[selectedIndex]?.label}` : "Add"}
                                    </div>
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h3 className="text-lg font-medium">Selected Questions</h3>
                          <p className="text-sm text-muted-foreground">
                            {manualSelectedQuestions.length}/{requiredQuestionCount} chosen
                          </p>
                        </div>
                      </div>
                      <div className="max-h-[460px] space-y-3 overflow-y-auto pr-1">
                        {manualSelectedQuestions.length === 0 ? (
                          <div className="rounded-lg border border-dashed bg-background px-4 py-6 text-sm text-muted-foreground">
                            Pick questions from the left panel to build the paper.
                          </div>
                        ) : (
                          manualSelectedQuestions.map((question, index) => (
                            <div key={question.id} className="rounded-lg border bg-background p-3 shadow-sm">
                              <div className="flex items-start justify-between gap-3">
                                <div className="space-y-2">
                                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                    Slot {blueprint[index]?.label} • Module {question.module_number}
                                  </p>
                                  <p className="text-sm leading-relaxed">{question.text}</p>
                                  <p className="text-xs text-muted-foreground">
                                    {question.course_outcome} • {question.bloom_level} • {question.difficulty} • {question.marks} marks
                                  </p>
                                </div>
                                <div className="flex shrink-0 flex-col gap-1">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => moveManualQuestion(index, -1)}
                                    disabled={index === 0}
                                  >
                                    <ArrowUp className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => moveManualQuestion(index, 1)}
                                    disabled={index === manualSelectedQuestions.length - 1}
                                  >
                                    <ArrowDown className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8 text-destructive"
                                    onClick={() => toggleManualQuestion(question.id)}
                                  >
                                    <X className="h-4 w-4" />
                                  </Button>
                                </div>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
              <CardFooter className="bg-muted/30 flex justify-between p-4 border-t">
                <Button variant="outline" onClick={() => setCurrentStep(1)}>Back</Button>
                <Button onClick={generateQuestions} disabled={isGenerating} className="px-8">
                  {isGenerating ? (
                    <>
                      <RotateCw className="mr-2 h-4 w-4 animate-spin" /> Generating...
                    </>
                  ) : (
                    <>
                      Generate Paper <Zap className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>
              </CardFooter>
            </motion.div>
          )}

          {currentStep === 3 && (
            <motion.div
              key="step3"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
            >
              <CardHeader className="flex flex-row items-center justify-between border-b pb-4">
                <div>
                  <CardTitle>Preview & Download</CardTitle>
                  <CardDescription>Review the generated paper before downloading.</CardDescription>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setCurrentStep(2)} disabled={isGenerating}>
                    <Edit className="mr-2 h-4 w-4" /> Edit
                  </Button>
                  <Button variant="outline" size="sm" onClick={generateQuestions} disabled={isGenerating}>
                    <RotateCw className={`mr-2 h-4 w-4 ${isGenerating ? "animate-spin" : ""}`} /> Regenerate
                  </Button>
                  <Button size="sm" onClick={handleDownload} disabled={!generatedPaper || isGenerating}>
                    <Download className="mr-2 h-4 w-4" /> Download .docx
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-0 bg-muted/30">
                {isGenerating && (
                  <div className="border-b bg-background px-6 py-5">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm font-semibold">Generation in progress</p>
                        <p className="text-sm text-muted-foreground">{generationStageMessage}</p>
                      </div>
                      <span className="text-sm font-semibold tabular-nums">{generationProgress}%</span>
                    </div>
                    <Progress value={generationProgress} className="mt-3 h-2" />
                    <p className="mt-3 text-xs text-muted-foreground">
                      {generatedPaper
                        ? "The last completed preview stays visible while the next version is assembled."
                        : "The preview will appear automatically as soon as the background job completes."}
                    </p>
                  </div>
                )}

                {generatedPaper ? (
                  <div className="p-6 overflow-x-auto">
                    <div className="min-w-[800px] bg-white p-8 shadow-sm border mx-auto text-black">
                      <EditablePaperPreview
                        formData={{
                          ...form.getValues(),
                          subjectName: selectedSubject?.name || 'Subject',
                          subjectCode: selectedSubject?.code || generatedPaper?.subject_code || "N/A",
                          department: form.getValues().department || generatedPaper?.department_name || "Department",
                          instructions,
                          coDescriptions,
                        }}
                        questions={generatedQuestions || []}
                        generatedPaper={generatedPaper}
                        onQuestionsChange={handleQuestionsChange}
                        isEditable
                      />
                    </div>
                  </div>
                ) : isGenerating ? (
                  <div className="p-6">
                    <div className="mx-auto max-w-3xl rounded-xl border bg-background p-6 shadow-sm">
                      <div className="space-y-4 animate-pulse">
                        <div className="h-6 w-48 rounded bg-muted" />
                        <div className="h-20 rounded bg-muted" />
                        <div className="h-10 rounded bg-muted" />
                        <div className="h-64 rounded bg-muted" />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-6">
                    <div className="rounded-xl border border-dashed bg-background px-6 py-12 text-center text-sm text-muted-foreground">
                      Generate a paper from Step 2 to see the preview here.
                    </div>
                    <div className="rounded-lg border border-dashed bg-background/70 px-4 py-3 text-xs text-muted-foreground">
                      <div className="flex flex-wrap items-center gap-4">
                        <span>Paper Quality Score: <span className="font-semibold text-foreground">{traceabilityInsights.qualityScore}</span></span>
                        <span>
                          {traceabilityInsights.lowConfidence === 0
                            ? "No low-confidence questions detected."
                            : `${traceabilityInsights.lowConfidence} low-confidence question(s) need review.`}
                        </span>
                        <span>
                          {traceabilityInsights.overlapWarnings === 0
                            ? "No major phrasing overlap detected."
                            : `${traceabilityInsights.overlapWarnings} overlap warning(s) detected.`}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* RAG Traceability Panel */}
                {useRag && generatedQuestions.length > 0 && generatedQuestions.some((q: any) => q.confidence != null || (q.source_documents && q.source_documents.length > 0)) && (
                  <div className="border-t p-6 space-y-4">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/></svg>
                      RAG Traceability Report
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      Every question below was generated from retrieved academic content. Confidence scores indicate how closely the output matches source material.
                    </p>

                    <div className="grid gap-3">
                      {generatedQuestions.map((q: any, idx: number) => {
                        const conf = q.confidence;
                        const confPct = conf != null ? Math.round(conf * 100) : null;
                        const overlapWarning = generatedQuestions.some((otherQuestion: any, otherIdx: number) => {
                          if (idx === otherIdx) {
                            return false;
                          }
                          return questionOverlapScore(q.text || "", otherQuestion.text || "") >= 0.72;
                        });
                        const confColor = confPct == null ? "bg-muted text-muted-foreground"
                          : confPct >= 80 ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
                          : confPct >= 50 ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
                          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400";
                        const docs: string[] = q.source_documents || [];
                        const validationWarnings: string[] = q.validation_warnings || [];
                        const validationErrors: string[] = q.validation_errors || [];

                        return (
                          <div key={idx} className="rounded-lg border bg-card p-3 space-y-2">
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex-1 min-w-0">
                                <p className="text-xs font-medium text-muted-foreground">
                                  Q{q.order_index || idx + 1} • {q.section_label || `Slot ${idx + 1}`}
                                </p>
                                <p className="text-sm mt-1 line-clamp-2">{q.text}</p>
                                <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                                  {q.module_number != null && <span>Module {q.module_number}</span>}
                                  {q.course_outcome && <span>{q.course_outcome}</span>}
                                  {q.bloom_level && <span>{q.bloom_level}</span>}
                                  {validationWarnings.length > 0 && (
                                    <span className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-800 dark:bg-sky-900/30 dark:text-sky-300">
                                      {validationWarnings.length} validation warning{validationWarnings.length > 1 ? "s" : ""}
                                    </span>
                                  )}
                                  {validationErrors.length > 0 && (
                                    <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-800 dark:bg-red-900/30 dark:text-red-300">
                                      {validationErrors.length} validation error{validationErrors.length > 1 ? "s" : ""}
                                    </span>
                                  )}
                                  {overlapWarning && (
                                    <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
                                      Overlap warning
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div className="shrink-0 flex flex-col items-end gap-1">
                                {confPct != null && (
                                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${confColor}`}>
                                    {confPct}% confidence
                                  </span>
                                )}
                              </div>
                            </div>
                            {docs.length > 0 && (
                              <div className="flex flex-wrap gap-1.5">
                                <span className="text-[10px] text-muted-foreground mr-1 self-center">Sources:</span>
                                {docs.map((doc, di) => (
                                  <span key={di} className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mr-1"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/></svg>
                                    {doc.length > 40 ? doc.slice(0, 37) + "…" : doc}
                                  </span>
                                ))}
                              </div>
                            )}
                            {(validationWarnings.length > 0 || validationErrors.length > 0) && (
                              <div className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
                                {validationWarnings.length > 0 && (
                                  <p>Warnings: {validationWarnings.join(" | ")}</p>
                                )}
                                {validationErrors.length > 0 && (
                                  <p>Errors: {validationErrors.join(" | ")}</p>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Overall summary */}
                    <div className="rounded-lg border bg-muted/40 p-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                      <div>
                        <p className="text-lg font-bold">{generatedQuestions.length}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Questions Generated</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold">{traceabilityInsights.highConfidence}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">High Confidence</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold">{traceabilityInsights.sourceDocuments}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Source Documents</p>
                      </div>
                      <div>
                        <p className="text-lg font-bold">
                          {generatedQuestions.filter((q: any) => q.confidence != null && q.confidence < 0.5).length === 0 ? "✓" : generatedQuestions.filter((q: any) => q.confidence != null && q.confidence < 0.5).length}
                        </p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                          {generatedQuestions.filter((q: any) => q.confidence != null && q.confidence < 0.5).length === 0 ? "All Validated" : "Low Confidence"}
                        </p>
                      </div>
                    </div>
                    <div className="rounded-lg border border-dashed bg-background/70 px-4 py-3 text-xs text-muted-foreground">
                      <div className="flex flex-wrap items-center gap-4">
                        <span>Paper Quality Score: <span className="font-semibold text-foreground">{traceabilityInsights.qualityScore}</span></span>
                        <span>
                          {traceabilityInsights.lowConfidence === 0
                            ? "No low-confidence questions detected."
                            : `${traceabilityInsights.lowConfidence} low-confidence question(s) need review.`}
                        </span>
                        <span>
                          {traceabilityInsights.overlapWarnings === 0
                            ? "No major phrasing overlap detected."
                            : `${traceabilityInsights.overlapWarnings} overlap warning(s) detected.`}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </div>
  );
}

function Zap(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}
