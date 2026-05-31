import { useCallback, useRef, useState } from "react";
import { Check, ImagePlus, Pencil, RefreshCw, RotateCcw, RotateCw, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import type { GeneratedPaper, PaperImageAttachment, PaperQuestion } from "@/lib/ai-api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PaperQuestionImages } from "@/components/paper-question-images";
import { getQuestionDisplayText, getQuestionImages } from "@/lib/paper-media";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface EditablePaperPreviewProps {
  formData?: {
    examType?: string;
    department?: string;
    subjectName?: string;
    subjectCode?: string;
    semester?: string;
    maxMarks?: number;
    batch?: string;
    duration?: string;
    dateOfIat?: string;
    teachingDept?: string;
    instructions?: string;
    coDescriptions?: Record<string, string>;
  };
  questions: PaperQuestion[];
  generatedPaper?: GeneratedPaper | null;
  onQuestionsChange?: (questions: PaperQuestion[]) => void;
  onRegenerateSlot?: (slotIndex: number, bloom: string, marks: number) => void;
  isEditable?: boolean;
}

interface EditState {
  /** Index of the question currently being edited, or null */
  editingIndex: number | null;
  /** Draft text for the question being edited */
  draftText: string;
  /** Draft CO */
  draftCO: string;
  /** Draft Bloom level */
  draftBloom: string;
}

type HistoryEntry = PaperQuestion[];

/* ------------------------------------------------------------------ */
/* Helpers (same as paper-preview.tsx)                                  */
/* ------------------------------------------------------------------ */

const DEFAULT_COS: Record<string, string> = {
  CO1: "", CO2: "", CO3: "", CO4: "", CO5: "",
};

function formatQuestionLabel(qn: number, sub: string) {
  return `${qn}(${sub})`;
}

function normalizeQuestionLabel(label: string | undefined, fallback: string) {
  const text = (label || fallback).trim();
  const match = text.match(/^(\d+)([a-z])$/i);
  return match ? formatQuestionLabel(Number(match[1]), match[2].toLowerCase()) : text;
}

function buildQuestionBlueprint(maxMarks: number) {
  if (maxMarks <= 50) {
    const patterns = [
      ...Array.from({ length: 4 }, () => [5, 5] as const),
      ...Array.from({ length: 6 }, () => [4, 6] as const),
    ];
    return patterns.flatMap(([partA, partB], index) => [
      { questionNumber: index + 1, subpart: "a", label: formatQuestionLabel(index + 1, "a"), marks: partA, moduleNumber: Math.floor(index / 2) + 1 },
      { questionNumber: index + 1, subpart: "b", label: formatQuestionLabel(index + 1, "b"), marks: partB, moduleNumber: Math.floor(index / 2) + 1 },
    ]);
  }
  const hundredMarkModules = [
    [1, [[1,"a",6],[1,"b",6],[1,"c",8],[2,"a",6],[2,"b",6],[2,"c",8]]],
    [2, [[3,"a",5],[3,"b",8],[3,"c",7],[4,"a",5],[4,"b",8],[4,"c",7]]],
    [3, [[5,"a",5],[5,"b",8],[5,"c",7],[6,"a",5],[6,"b",8],[6,"c",7]]],
    [4, [[7,"a",10],[7,"b",10],[8,"a",10],[8,"b",10]]],
    [5, [[9,"a",10],[9,"b",10],[10,"a",10],[10,"b",10]]],
  ] as const;
  return hundredMarkModules.flatMap(([moduleNumber, rows]) =>
    rows.map(([questionNumber, subpart, marks]) => ({
      questionNumber, subpart,
      label: formatQuestionLabel(questionNumber, subpart),
      marks, moduleNumber,
    })),
  );
}

function buildPercentageMap(values: Record<string, any> | undefined, keys: string[]) {
  return Object.fromEntries(keys.map((key) => [key, values?.[key] ?? 0]));
}

type PaperRow =
  | { type: "module"; title: string; key: string }
  | { type: "or"; key: string }
  | { type: "question"; key: string; index: number; qno: string; text: string; marks: number; co: string; rbtl: string; attachedImages: PaperImageAttachment[] };

function buildPaperRows(
  maxMarks: number,
  blueprint: ReturnType<typeof buildQuestionBlueprint>,
  questions: PaperQuestion[],
): PaperRow[] {
  const rows: PaperRow[] = [];
  blueprint.forEach((slot, index) => {
    const question = questions[index];
    const previousSlot = index > 0 ? blueprint[index - 1] : null;
    if (maxMarks > 50 && (!previousSlot || previousSlot.moduleNumber !== slot.moduleNumber)) {
      rows.push({ type: "module", title: `Module - ${slot.moduleNumber}`, key: `module-${slot.moduleNumber}` });
    }
    if (slot.subpart === "a" && slot.questionNumber % 2 === 0) {
      rows.push({ type: "or", key: `or-${slot.questionNumber}` });
    }
    rows.push({
      type: "question", key: `question-${slot.label}`, index,
      qno: normalizeQuestionLabel(question?.section_label, slot.label),
      text: getQuestionDisplayText(question || { text: "" }), marks: question?.custom_marks ?? slot.marks,
      co: question?.course_outcome || "", rbtl: question?.bloom_level || "",
      attachedImages: getQuestionImages(question || { text: "", attached_images: [] }),
    });
  });
  return rows;
}

const BLOOM_OPTIONS = ["L1", "L2", "L3", "L4", "L5", "L6"];
const CO_OPTIONS = ["CO1", "CO2", "CO3", "CO4", "CO5"];

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read image"));
    reader.readAsDataURL(file);
  });
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function EditablePaperPreview({
  formData, questions, generatedPaper,
  onQuestionsChange, onRegenerateSlot,
  isEditable = true,
}: EditablePaperPreviewProps) {
  /* Edit state */
  const [editState, setEditState] = useState<EditState>({
    editingIndex: null, draftText: "", draftCO: "", draftBloom: "",
  });
  const [editedIndices, setEditedIndices] = useState<Set<number>>(new Set());
  const [imagePickerIndex, setImagePickerIndex] = useState<number | null>(null);

  /* Undo/Redo */
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const cloneQuestions = useCallback((qs: PaperQuestion[]) => (
    qs.map((q) => ({
      ...q,
      attached_images: q.attached_images?.map((image) => ({ ...image })) || [],
    }))
  ), []);

  const commitQuestions = useCallback((updated: PaperQuestion[]) => {
    setHistory((prev) => {
      const base = historyIndex >= 0
        ? prev.slice(0, historyIndex + 1)
        : [cloneQuestions(questions)];
      return [...base, cloneQuestions(updated)];
    });
    setHistoryIndex((prev) => (prev < 0 ? 1 : prev + 1));
    onQuestionsChange?.(updated);
  }, [cloneQuestions, historyIndex, onQuestionsChange, questions]);

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < history.length - 1;

  const handleUndo = useCallback(() => {
    if (!canUndo) return;
    const prev = history[historyIndex - 1];
    setHistoryIndex((i) => i - 1);
    onQuestionsChange?.(prev);
  }, [canUndo, history, historyIndex, onQuestionsChange]);

  const handleRedo = useCallback(() => {
    if (!canRedo) return;
    const next = history[historyIndex + 1];
    setHistoryIndex((i) => i + 1);
    onQuestionsChange?.(next);
  }, [canRedo, history, historyIndex, onQuestionsChange]);

  /* Paper config */
  const paperConfig = generatedPaper?.ai_config ?? {};
  const coverage = generatedPaper?.coverage_stats ?? {};
  const coPercentages = buildPercentageMap(coverage?.percentages?.co, ["CO1", "CO2", "CO3", "CO4", "CO5"]);
  const modulePercentages = buildPercentageMap(coverage?.percentages?.modules, ["1", "2", "3", "4", "5"]);

  const defaults = {
    examType: generatedPaper?.exam_type || formData?.examType || "First Internal Assessment Test (IAT-1)",
    department: generatedPaper?.department_name || formData?.department || "Artificial Intelligence and Machine Learning",
    subjectName: generatedPaper?.subject_name || formData?.subjectName || "Machine Learning",
    subjectCode: generatedPaper?.subject_code || formData?.subjectCode || "21AI51",
    semester: generatedPaper?.semester || formData?.semester || "5",
    maxMarks: generatedPaper?.max_marks ?? formData?.maxMarks ?? 50,
    batch: generatedPaper?.batch || formData?.batch || "2022-26",
    duration: generatedPaper?.duration_minutes ? `${generatedPaper.duration_minutes} Minutes` : formData?.duration || "90 Minutes",
    dateOfIat: generatedPaper?.exam_date || formData?.dateOfIat || "To be announced",
    teachingDept: generatedPaper?.teaching_department || formData?.teachingDept || "AIML",
    instructions: formData?.instructions || paperConfig.instructions || "Instruction: Answer the following questions",
    coDescriptions: { ...DEFAULT_COS, ...(paperConfig.co_descriptions ?? {}), ...(formData?.coDescriptions ?? {}) },
    templateNote: paperConfig.template_note || ((generatedPaper?.max_marks || formData?.maxMarks || 50) >= 100
      ? "Answer any FIVE full questions, choosing at least ONE question from each MODULE" : ""),
  };

  const blueprint = buildQuestionBlueprint(defaults.maxMarks || 50);
  const previewQuestions = questions.slice(0, blueprint.length);
  const paperRows = buildPaperRows(defaults.maxMarks || 50, blueprint, previewQuestions);
  const availableExtractedImages = (generatedPaper?.ai_config?.image_pool || []) as PaperImageAttachment[];
  const activeImageQuestion = imagePickerIndex != null ? previewQuestions[imagePickerIndex] : null;

  /* Edit handlers */
  const startEditing = (index: number) => {
    const q = previewQuestions[index];
    if (!q || !isEditable) return;
    setEditState({
      editingIndex: index,
      draftText: q.text || "",
      draftCO: q.course_outcome || "CO1",
      draftBloom: q.bloom_level || "L1",
    });
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const cancelEditing = () => {
    setEditState({ editingIndex: null, draftText: "", draftCO: "", draftBloom: "" });
  };

  const saveEditing = () => {
    const idx = editState.editingIndex;
    if (idx === null) return;
    const updated = questions.map((q, i) =>
      i === idx ? { ...q, text: editState.draftText, course_outcome: editState.draftCO, bloom_level: editState.draftBloom } : q,
    );
    setEditedIndices((prev) => new Set(prev).add(idx));
    commitQuestions(updated);
    cancelEditing();
    toast.success("Question updated");
  };

  const handleRegenerate = (index: number) => {
    const slot = blueprint[index];
    const q = previewQuestions[index];
    if (!slot) return;
    onRegenerateSlot?.(index, q?.bloom_level || "L2", slot.marks);
    toast.info(`Regenerating slot ${slot.label}...`);
  };

  const attachImageToQuestion = (questionIndex: number, attachment: PaperImageAttachment) => {
    const updated = questions.map((question, index) =>
      index === questionIndex
        ? {
            ...question,
            attached_images: [
              ...(question.attached_images || []),
              attachment,
            ],
          }
        : question,
    );
    setEditedIndices((prev) => new Set(prev).add(questionIndex));
    commitQuestions(updated);
  };

  const removeQuestionImage = (questionIndex: number, imageIndex: number) => {
    const updated = questions.map((question, index) =>
      index === questionIndex
        ? {
            ...question,
            attached_images: (question.attached_images || []).filter((_, idx) => idx !== imageIndex),
          }
        : question,
    );
    setEditedIndices((prev) => new Set(prev).add(questionIndex));
    commitQuestions(updated);
  };

  const handleCustomImageUpload = async (questionIndex: number, file: File | null) => {
    if (!file) {
      return;
    }
    try {
      const objectUrl = URL.createObjectURL(file);
      const dataUrl = await readFileAsDataUrl(file);
      attachImageToQuestion(questionIndex, {
        is_custom: true,
        object_url: objectUrl,
        data_url: dataUrl,
        file_name: file.name,
        caption: file.name.replace(/\.[^.]+$/, ""),
        local_file: file,
      });
      toast.success("Custom image inserted");
    } catch {
      toast.error("Unable to load the selected image");
    }
  };

  /* Editing toolbar */
  const editToolbar = isEditable && (
    <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-slate-200 bg-slate-50/95 px-4 py-2 backdrop-blur-sm print:hidden">
      <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Edit Mode</span>
      <div className="flex-1" />
      <Button variant="ghost" size="sm" disabled={!canUndo} onClick={handleUndo} className="h-7 gap-1 text-xs">
        <RotateCcw className="h-3.5 w-3.5" /> Undo
      </Button>
      <Button variant="ghost" size="sm" disabled={!canRedo} onClick={handleRedo} className="h-7 gap-1 text-xs">
        <RotateCw className="h-3.5 w-3.5" /> Redo
      </Button>
      {editedIndices.size > 0 && (
        <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
          {editedIndices.size} edited
        </span>
      )}
    </div>
  );

  /* Render a question row */
  const renderQuestionRow = (row: PaperRow & { type: "question" }) => {
    const isEditing = editState.editingIndex === row.index;
    const wasEdited = editedIndices.has(row.index);

    if (isEditing) {
      return (
        <tr key={row.key} className="bg-blue-50/60">
          <td className="border border-black px-2 py-1 align-top text-center">{row.qno}</td>
          <td className="border border-black px-1 py-1 align-top" colSpan={4}>
            <div className="space-y-2">
              <textarea
                ref={textareaRef}
                value={editState.draftText}
                onChange={(e) => setEditState((s) => ({ ...s, draftText: e.target.value }))}
                className="w-full min-h-[60px] rounded border border-blue-300 bg-white px-2 py-1 text-[11px] outline-none focus:ring-2 focus:ring-blue-400 resize-y"
                rows={3}
              />
              <div className="flex items-center gap-2">
                <Select value={editState.draftBloom} onValueChange={(v) => setEditState((s) => ({ ...s, draftBloom: v }))}>
                  <SelectTrigger className="h-7 w-20 text-[10px]"><SelectValue /></SelectTrigger>
                  <SelectContent>{BLOOM_OPTIONS.map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}</SelectContent>
                </Select>
                <Select value={editState.draftCO} onValueChange={(v) => setEditState((s) => ({ ...s, draftCO: v }))}>
                  <SelectTrigger className="h-7 w-20 text-[10px]"><SelectValue /></SelectTrigger>
                  <SelectContent>{CO_OPTIONS.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                </Select>
                <div className="flex-1" />
                <Button size="sm" variant="ghost" onClick={cancelEditing} className="h-7 gap-1 text-xs">
                  <X className="h-3 w-3" /> Cancel
                </Button>
                <Button size="sm" onClick={saveEditing} className="h-7 gap-1 text-xs">
                  <Check className="h-3 w-3" /> Save
                </Button>
              </div>
            </div>
          </td>
        </tr>
      );
    }

    return (
      <tr
        key={row.key}
        className={`group relative ${wasEdited ? "bg-amber-50/40" : ""} ${isEditable ? "cursor-pointer hover:bg-blue-50/30" : ""}`}
        onDoubleClick={() => isEditable && startEditing(row.index)}
      >
        <td className="break-words border border-black px-2 py-1 align-top text-center">{row.qno}</td>
        <td className="whitespace-pre-line break-words border border-black px-2 py-1 align-top relative">
          <div className="whitespace-pre-line">{row.text}</div>
          <PaperQuestionImages attachments={row.attachedImages} />
          {wasEdited && <span className="absolute top-0.5 right-1 h-1.5 w-1.5 rounded-full bg-amber-400" title="Edited" />}
          {isEditable && (
            <span className="absolute right-1 top-1 hidden gap-0.5 group-hover:flex print:hidden">
              <button onClick={() => startEditing(row.index)} className="rounded bg-white/90 p-0.5 shadow-sm hover:bg-blue-100" title="Edit">
                <Pencil className="h-3 w-3 text-blue-600" />
              </button>
              <button onClick={() => setImagePickerIndex(row.index)} className="rounded bg-white/90 p-0.5 shadow-sm hover:bg-amber-100" title="Insert image">
                <ImagePlus className="h-3 w-3 text-amber-600" />
              </button>
              {onRegenerateSlot && (
                <button onClick={() => handleRegenerate(row.index)} className="rounded bg-white/90 p-0.5 shadow-sm hover:bg-green-100" title="Regenerate">
                  <RefreshCw className="h-3 w-3 text-green-600" />
                </button>
              )}
            </span>
          )}
        </td>
        <td className="break-words border border-black px-2 py-1 align-top text-center">{row.marks}</td>
        <td className="break-words border border-black px-2 py-1 align-top text-center">{row.co}</td>
        <td className="break-words border border-black px-2 py-1 align-top text-center">{row.rbtl}</td>
      </tr>
    );
  };

  return (
    <div className="flex flex-col">
      {editToolbar}
      <div className="mx-auto w-full max-w-[820px] bg-white px-4 py-4 font-sans text-[11px] text-black">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-black pb-3">
          <img src="/dsatm-seal.svg" alt="DSATM seal" className="h-14 w-14 object-contain" />
          <div className="flex-1 border-r border-black pr-3">
            <p className="text-[12px] font-bold">Dayananda Sagar Academy of Technology &amp; Management</p>
            <p className="text-[10px]">(Autonomous Institute under VTU)</p>
          </div>
          <div className="min-w-[220px] text-[10px] leading-tight">
            <p>Affiliated to <span className="text-red-600">VTU</span></p>
            <p>Approved by <span className="text-red-600">AICTE</span></p>
            <p>Accredited by <span className="text-red-600">NAAC</span> with <span className="text-red-600">A+</span> Grade</p>
            <p>6 Programs Accredited by <span className="text-red-600">NBA</span></p>
            <p>(CSE, ISE, ECE, EEE, MECH, CV)</p>
          </div>
          <img src="/iqac-seal.svg" alt="IQAC seal" className="h-14 w-14 object-contain" />
        </div>

        {/* USN Row */}
        <div className="mt-3 flex items-center justify-end gap-2 text-[11px]">
          <span>USN:</span>
          <div className="flex gap-[2px]">
            {Array.from({ length: 10 }).map((_, i) => <span key={i} className="h-6 w-6 border border-black" />)}
          </div>
        </div>

        <h2 className="mt-3 text-center text-[15px] font-bold">Department of {defaults.department}</h2>
        <div className="mt-3 border border-black text-center text-[13px] font-bold">
          <div className="px-3 py-1.5">{defaults.examType}</div>
        </div>

        {/* Meta Table */}
        <table className="mt-3 w-full border-collapse text-[11px]">
          <tbody>
            <tr>
              <td className="border border-black px-2 py-1 font-bold">Subject:</td>
              <td className="border border-black px-2 py-1">{defaults.subjectName}</td>
              <td className="border border-black px-2 py-1 font-bold">Subject Code:</td>
              <td className="border border-black px-2 py-1">{defaults.subjectCode}</td>
            </tr>
            <tr>
              <td className="border border-black px-2 py-1 font-bold">Semester:</td>
              <td className="border border-black px-2 py-1">{defaults.semester}</td>
              <td className="border border-black px-2 py-1 font-bold">Max. Marks:</td>
              <td className="border border-black px-2 py-1">{defaults.maxMarks}</td>
            </tr>
            <tr>
              <td className="border border-black px-2 py-1 font-bold">Batch:</td>
              <td className="border border-black px-2 py-1">{defaults.batch}</td>
              <td className="border border-black px-2 py-1 font-bold">Duration:</td>
              <td className="border border-black px-2 py-1">{defaults.duration}</td>
            </tr>
            <tr>
              <td className="border border-black px-2 py-1 font-bold">Date of IAT:</td>
              <td className="border border-black px-2 py-1">{defaults.dateOfIat}</td>
              <td className="border border-black px-2 py-1 font-bold">Teaching Department:</td>
              <td className="border border-black px-2 py-1">{defaults.teachingDept}</td>
            </tr>
            <tr>
              <td className="border border-black px-2 py-1 font-bold">RBT Levels:</td>
              <td className="border border-black px-2 py-1" colSpan={3}>
                L1-Remember, L2-Understand, L3-Apply, L4-Analyze, L5-Evaluate, L6-Create
              </td>
            </tr>
          </tbody>
        </table>

        <p className="mt-4 text-center text-[11px] italic">{defaults.instructions}</p>
        {defaults.templateNote && (
          <div className="mt-3 text-[11px]">
            <p className="font-bold">Note:</p>
            <p className="font-bold">{defaults.templateNote}</p>
          </div>
        )}

        {/* Question Table — Editable */}
        <table className="mt-2 w-full table-fixed border-collapse text-[11px]">
          <colgroup>
            <col className="w-[8%]" />
            <col className="w-[66%]" />
            <col className="w-[10%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
          </colgroup>
          <thead>
            <tr>
              <th className="break-words border border-black px-2 py-1 text-center leading-tight">Q<br />No</th>
              <th className="break-words border border-black px-2 py-1 text-center">Questions</th>
              <th className="break-words border border-black px-2 py-1 text-center">Marks</th>
              <th className="break-words border border-black px-2 py-1 text-center">COs</th>
              <th className="break-words border border-black px-2 py-1 text-center">RBTL</th>
            </tr>
          </thead>
          <tbody>
            {paperRows.map((row) => {
              if (row.type === "module") {
                return (
                  <tr key={row.key} className="bg-slate-100">
                    <td colSpan={5} className="border border-black px-2 py-1 text-center font-bold">{row.title}</td>
                  </tr>
                );
              }
              if (row.type === "or") {
                return (
                  <tr key={row.key}>
                    <td colSpan={5} className="border border-black px-2 py-1 text-center font-semibold">OR</td>
                  </tr>
                );
              }
              return renderQuestionRow(row);
            })}
          </tbody>
        </table>

        {/* CO Descriptions */}
        <div className="mt-8">
          <p className="mb-1 text-center text-[11px] font-bold">
            Course Outcomes (COs):&nbsp; At the end of the Course, the Student will be able to:
          </p>
          <table className="w-full border-collapse text-[11px]">
            <tbody>
              {["CO1", "CO2", "CO3", "CO4", "CO5"].map((co) => (
                <tr key={co}>
                  <td className="w-12 border border-black px-2 py-1 font-bold">{co}</td>
                  <td className="border border-black px-2 py-1">{defaults.coDescriptions[co] || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Coverage Tables */}
        <div className="mt-10 space-y-5">
          <div>
            <p className="mb-1 text-[11px] font-bold">Percentage of CO Coverage</p>
            <table className="w-full border-collapse text-[11px]">
              <tbody>
                <tr>
                  <td className="border border-black px-2 py-1 text-center font-bold">Course Outcomes</td>
                  {["CO1","CO2","CO3","CO4","CO5"].map((co) => (
                    <td key={co} className="border border-black px-2 py-1 text-center font-bold">{co}</td>
                  ))}
                </tr>
                <tr>
                  <td className="border border-black px-2 py-1 text-center font-bold">Percentage</td>
                  {["CO1","CO2","CO3","CO4","CO5"].map((co) => (
                    <td key={co} className="border border-black px-2 py-1 text-center">{coPercentages[co]}</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <p className="mb-1 text-[11px] font-bold">Percentage of Syllabus coverage</p>
            <table className="w-full border-collapse text-[11px]">
              <tbody>
                <tr>
                  <td className="border border-black px-2 py-1 text-center font-bold">Modules Covered</td>
                  {["1","2","3","4","5"].map((m) => (
                    <td key={m} className="border border-black px-2 py-1 text-center font-bold">{m}</td>
                  ))}
                </tr>
                <tr>
                  <td className="border border-black px-2 py-1 text-center font-bold">Percentage</td>
                  {["1","2","3","4","5"].map((m) => (
                    <td key={m} className="border border-black px-2 py-1 text-center">{modulePercentages[m]}</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <Dialog open={imagePickerIndex !== null} onOpenChange={(open) => { if (!open) setImagePickerIndex(null); }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Insert Image</DialogTitle>
            <DialogDescription>
              Attach an uploaded image or an extracted document image to this question.
            </DialogDescription>
          </DialogHeader>
          {imagePickerIndex != null && (
            <div className="space-y-4">
              <div className="rounded-md border bg-slate-50 p-3 text-sm text-slate-700">
                {activeImageQuestion ? getQuestionDisplayText(activeImageQuestion) : ""}
              </div>

              {activeImageQuestion?.attached_images?.length ? (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Attached Images</p>
                  <div className="space-y-2">
                    {activeImageQuestion.attached_images.map((image, idx) => (
                      <div key={`${image.image_id || image.object_url || image.image_path || "attached"}-${idx}`} className="flex items-center justify-between rounded-md border p-2">
                        <span className="text-xs text-slate-700">
                          {image.caption || image.file_name || image.document_name || "Question image"}
                        </span>
                        <Button type="button" variant="ghost" size="sm" onClick={() => removeQuestionImage(imagePickerIndex, idx)}>
                          <Trash2 className="mr-1 h-3.5 w-3.5" /> Remove
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Upload Custom Image</p>
                <Input
                  type="file"
                  accept=".png,.jpg,.jpeg,.webp,.gif"
                  onChange={(event) => handleCustomImageUpload(imagePickerIndex, event.target.files?.[0] || null)}
                />
              </div>

              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Extracted Image Pool</p>
                {availableExtractedImages.length > 0 ? (
                  <div className="grid max-h-[360px] grid-cols-2 gap-3 overflow-y-auto pr-1">
                    {availableExtractedImages.map((image, idx) => (
                      <button
                        key={`${image.image_id || image.image_path || "pool"}-${idx}`}
                        type="button"
                        onClick={() => attachImageToQuestion(imagePickerIndex, { ...image })}
                        className="rounded-md border p-3 text-left transition-colors hover:border-primary hover:bg-slate-50"
                      >
                        <p className="text-xs font-semibold text-slate-800">
                          {image.caption || image.document_name || `Extracted image ${idx + 1}`}
                        </p>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {image.document_name || "Academic document"}{image.source_page ? ` - page ${image.source_page}` : ""}
                        </p>
                        {image.keywords?.length ? (
                          <p className="mt-2 line-clamp-2 text-[10px] text-slate-500">
                            {image.keywords.slice(0, 5).join(", ")}
                          </p>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
                    No extracted images are available for this paper yet.
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
