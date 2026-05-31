import { useState } from "react";
import { Plus, BookOpen, Clock, Settings, Upload, ArrowLeft, CheckCircle2, AlertTriangle, File, FileText, BarChart2, PlusCircle, Trash2, Loader2, Sparkles, AlertCircle } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import { authFetch, useSyllabus, useAcademicDocuments, useUploadAcademicDocument, useDeleteAcademicDocument, useKnowledgeChunks, useTopicCoverage } from "@/lib/academic-api";
import { useQuestions } from "@/lib/ai-api";

interface Subject {
  id: number;
  name: string;
  code: string;
  semester: number;
  academic_year: string | null;
  credits: number | null;
  max_marks: number;
  regulation_scheme: string | null;
  ia_pattern: string | null;
  exam_duration: number | null;
  number_of_modules: number;
  theory_lab_type: string | null;
  pattern_type: string | null;
  department: string | null;
}

export default function Subjects() {
  const queryClient = useQueryClient();
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [activeSubject, setActiveSubject] = useState<Subject | null>(null);
  const [activeTab, setActiveTab] = useState("syllabus");
  const [syllabusUploading, setSyllabusUploading] = useState(false);
  const [notesUploading, setNotesUploading] = useState(false);

  // Subjects query
  const { data: subjects = [], isLoading: loadingSubjects } = useQuery<Subject[]>({
    queryKey: ["subjects"],
    queryFn: () => authFetch<Subject[]>("/subjects"),
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<Subject>) =>
      authFetch<Subject>("/subjects", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
      toast.success("Subject created successfully!");
      setIsAddOpen(false);
    },
    onError: (err: any) => {
      toast.error(err.message || "Failed to create subject");
    },
  });

  const uploadMutation = useUploadAcademicDocument();
  const deleteMutation = useDeleteAcademicDocument();

  // Active Subject hooks
  const { data: syllabus, isLoading: loadingSyllabus } = useSyllabus(activeSubject?.id || 0);
  const { data: docsRes, isLoading: loadingDocs } = useAcademicDocuments(activeSubject?.id);
  const { data: chunks = [], isLoading: loadingChunks } = useKnowledgeChunks({ subjectId: activeSubject?.id });
  const { data: coverageData, isLoading: loadingCoverage } = useTopicCoverage(activeSubject?.id || 0);
  const { data: questions = [], isLoading: loadingQuestions } = useQuestions(activeSubject?.id);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const data = {
      name: formData.get("name") as string,
      code: formData.get("code") as string,
      semester: parseInt(formData.get("semester") as string, 10),
      academic_year: formData.get("academic_year") as string,
      credits: parseInt(formData.get("credits") as string, 10),
      max_marks: parseInt(formData.get("max_marks") as string, 10),
      regulation_scheme: formData.get("regulation_scheme") as string,
      ia_pattern: formData.get("ia_pattern") as string,
      exam_duration: parseInt(formData.get("exam_duration") as string, 10),
      number_of_modules: parseInt(formData.get("number_of_modules") as string, 10),
      theory_lab_type: formData.get("theory_lab_type") as string,
      pattern_type: formData.get("pattern_type") as string,
      department: formData.get("department") as string,
    };
    createMutation.mutate(data);
  };

  const handleSyllabusUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !activeSubject) return;
    setSyllabusUploading(true);
    try {
      await uploadMutation.mutateAsync({
        subjectId: activeSubject.id,
        file,
        documentType: "syllabus",
      });
      queryClient.invalidateQueries({ queryKey: ["syllabus", activeSubject.id] });
      toast.success("Syllabus processed and topic tree built successfully!");
    } catch (err: any) {
      toast.error(err.message || "Failed to process syllabus");
    } finally {
      setSyllabusUploading(false);
    }
  };

  const handleNotesUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !activeSubject) return;
    setNotesUploading(true);
    try {
      await uploadMutation.mutateAsync({
        subjectId: activeSubject.id,
        file,
        documentType: "notes",
      });
      queryClient.invalidateQueries({ queryKey: ["academic-documents", activeSubject.id] });
      queryClient.invalidateQueries({ queryKey: ["academic-chunks", { subjectId: activeSubject.id }] });
      toast.success("Lecture notes uploaded and successfully chunked!");
    } catch (err: any) {
      toast.error(err.message || "Failed to upload notes");
    } finally {
      setNotesUploading(false);
    }
  };

  const handleDeleteDoc = async (id: number) => {
    if (!confirm("Are you sure you want to delete this document and all its chunks?")) return;
    try {
      await deleteMutation.mutateAsync(id);
      toast.success("Document deleted.");
      queryClient.invalidateQueries({ queryKey: ["academic-documents", activeSubject?.id] });
      queryClient.invalidateQueries({ queryKey: ["academic-chunks", { subjectId: activeSubject?.id }] });
    } catch (err: any) {
      toast.error(err.message || "Failed to delete document");
    }
  };

  // Main Render - Split into List vs Workspace view
  if (activeSubject) {
    const notesDocs = docsRes?.documents?.filter(doc => doc.document_type === "notes") || [];
    const bankDocs = docsRes?.documents?.filter(doc => doc.document_type === "question_bank") || [];
    const pastDocs = docsRes?.documents?.filter(doc => doc.document_type === "previous_paper") || [];

    return (
      <div className="space-y-6 max-w-6xl">
        {/* Back navigation & Workspace header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-5">
          <div className="flex items-start gap-4">
            <Button variant="outline" size="icon" onClick={() => setActiveSubject(null)} className="h-10 w-10 shrink-0">
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-bold font-serif tracking-tight text-foreground">{activeSubject.name}</h1>
                <Badge variant="secondary" className="font-mono">{activeSubject.code}</Badge>
                <Badge className="bg-primary/10 text-primary hover:bg-primary/20">Sem {activeSubject.semester}</Badge>
              </div>
              <p className="text-muted-foreground text-sm mt-1">
                {activeSubject.department} Department · {activeSubject.pattern_type} Model Assessment Workspace
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="px-3 py-1 text-xs">
              <Sparkles className="h-3 w-3 mr-1 text-primary animate-pulse" /> VTU Compliant
            </Badge>
          </div>
        </div>

        {/* Tab Selection */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid grid-cols-5 w-full max-w-2xl bg-muted/60 p-1 rounded-xl">
            <TabsTrigger value="syllabus" className="rounded-lg text-xs py-2">Syllabus</TabsTrigger>
            <TabsTrigger value="notes" className="rounded-lg text-xs py-2">Notes</TabsTrigger>
            <TabsTrigger value="qbank" className="rounded-lg text-xs py-2">Question Bank</TabsTrigger>
            <TabsTrigger value="papers" className="rounded-lg text-xs py-2">Past Papers</TabsTrigger>
            <TabsTrigger value="analytics" className="rounded-lg text-xs py-2">Analytics</TabsTrigger>
          </TabsList>

          {/* TAB 1: Syllabus collapsible topics and tree */}
          <TabsContent value="syllabus" className="mt-6 space-y-6 animate-in fade-in-50 duration-200">
            <div className="grid md:grid-cols-3 gap-6">
              {/* Left panel: Upload and CO descriptions */}
              <div className="md:col-span-1 space-y-6">
                <Card className="border-border/60 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-base font-semibold">Syllabus Authority</CardTitle>
                    <CardDescription>
                      Upload the official syllabus PDF or DOCX. This defines the hard boundary constraints for question generation.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="relative rounded-xl border border-dashed p-6 text-center hover:bg-muted/10 transition-colors">
                      <input
                        type="file"
                        id="syl-upload-file"
                        accept=".pdf,.docx,.txt"
                        className="hidden"
                        onChange={handleSyllabusUpload}
                        disabled={syllabusUploading}
                      />
                      <label htmlFor="syl-upload-file" className="cursor-pointer block">
                        {syllabusUploading ? (
                          <div className="flex flex-col items-center justify-center gap-2">
                            <Loader2 className="h-8 w-8 text-primary animate-spin" />
                            <span className="text-xs font-semibold text-muted-foreground">Parsing Topic Tree...</span>
                          </div>
                        ) : (
                          <div className="flex flex-col items-center justify-center gap-2">
                            <Upload className="h-8 w-8 text-muted-foreground/60" />
                            <span className="text-xs font-semibold text-primary">Upload Syllabus Document</span>
                            <span className="text-[10px] text-muted-foreground">PDF or DOCX up to 10MB</span>
                          </div>
                        )}
                      </label>
                    </div>

                    {syllabus?.created_at && (
                      <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 p-3 border border-emerald-500/20">
                        <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                        <span className="text-xs text-emerald-800 font-medium">Syllabus Graph is loaded and active</span>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* CO definitions list */}
                <Card className="border-border/60 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-base font-semibold">Course Outcomes (COs)</CardTitle>
                    <CardDescription>Definitions mapped for Printed Question Papers</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {loadingSyllabus ? (
                      <div className="text-center text-xs text-muted-foreground">Loading COs...</div>
                    ) : syllabus?.co_json && Object.keys(syllabus.co_json).length > 0 ? (
                      Object.entries(syllabus.co_json).map(([co, desc]) => (
                        <div key={co} className="p-2.5 rounded-lg bg-muted/20 border border-muted/50 text-xs">
                          <span className="font-bold text-primary block mb-1">{co}</span>
                          <span className="text-muted-foreground leading-normal">{desc}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-center py-6 text-xs text-muted-foreground flex flex-col items-center gap-1.5">
                        <AlertCircle className="h-4 w-4 text-amber-500" />
                        <span>Syllabus not processed yet. Upload a syllabus to automatically extract Course Outcomes.</span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Right panel: Collapsible Topic Tree */}
              <div className="md:col-span-2 space-y-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-1">Visual Syllabus Topic Tree</h3>
                
                {loadingSyllabus ? (
                  <div className="py-20 text-center text-muted-foreground">Loading topic tree...</div>
                ) : syllabus?.modules_json && syllabus.modules_json.length > 0 ? (
                  <div className="space-y-4">
                    {syllabus.modules_json.map((mod: any) => (
                      <Card key={mod.module} className="border-border/60 shadow-sm overflow-hidden group hover:border-primary/20 transition-all">
                        <CardHeader className="bg-muted/30 py-3.5 px-4 flex flex-row items-center justify-between">
                          <div>
                            <CardTitle className="text-sm font-bold text-foreground">
                              Module {mod.module}: {mod.title || "Module Details"}
                            </CardTitle>
                          </div>
                          <Badge variant="outline" className="bg-background text-xs font-semibold px-2 py-0.5">
                            {mod.topics?.length || 0} Syllabus Topics
                          </Badge>
                        </CardHeader>
                        <CardContent className="p-4">
                          <ul className="grid sm:grid-cols-2 gap-2">
                            {mod.topics?.map((topic: string, index: number) => (
                              <li key={index} className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/10 p-2.5 rounded-lg border border-border/40 hover:bg-muted/20 transition-colors">
                                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                                <span className="leading-normal">{topic}</span>
                              </li>
                            ))}
                          </ul>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <div className="py-20 text-center border border-dashed rounded-xl flex flex-col items-center justify-center p-6 bg-card">
                    <BookOpen className="h-10 w-10 text-muted-foreground/60 mb-2" />
                    <h4 className="font-semibold text-sm mb-1">No topics found</h4>
                    <p className="text-xs text-muted-foreground max-w-sm mb-4">
                      Upload a syllabus document PDF or Word file to automatically extract structure, modules, units, and Course Outcomes.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          {/* TAB 2: Notes / Lecture handbooks */}
          <TabsContent value="notes" className="mt-6 space-y-6 animate-in fade-in-50 duration-200">
            <div className="grid md:grid-cols-5 gap-6">
              {/* Left Column: Processed Notes Docs list */}
              <div className="md:col-span-2 space-y-4">
                <Card className="border-border/60 shadow-sm">
                  <CardHeader className="pb-3 flex flex-row items-center justify-between">
                    <div>
                      <CardTitle className="text-base font-semibold">Class Notes Handouts</CardTitle>
                      <CardDescription>Uploaded lecture chunks for RAG context</CardDescription>
                    </div>
                    <label htmlFor="notes-upload" className="cursor-pointer">
                      <Button variant="outline" size="sm" asChild className="pointer-events-none">
                        <span>
                          {notesUploading ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Plus className="h-3.5 w-3.5 mr-1" />}
                          Add Notes
                        </span>
                      </Button>
                      <input
                        type="file"
                        id="notes-upload"
                        className="hidden"
                        accept=".pdf,.docx,.txt"
                        onChange={handleNotesUpload}
                        disabled={notesUploading}
                      />
                    </label>
                  </CardHeader>
                  <CardContent className="p-3">
                    {loadingDocs ? (
                      <div className="text-center py-6 text-xs text-muted-foreground">Loading Notes...</div>
                    ) : notesDocs.length > 0 ? (
                      <div className="space-y-2">
                        {notesDocs.map(doc => (
                          <div key={doc.id} className="flex items-center justify-between p-3 rounded-lg border border-border/40 hover:bg-muted/15 group transition-colors">
                            <div className="flex items-center gap-2 min-w-0">
                              <FileText className="h-4 w-4 text-primary shrink-0" />
                              <div className="min-w-0">
                                <span className="text-xs font-semibold block truncate text-foreground">{doc.file_name}</span>
                                <span className="text-[10px] text-muted-foreground block">{doc.total_chunks} chunks · processed</span>
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteDoc(doc.id)}
                              className="h-7 w-7 text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-10 text-xs text-muted-foreground flex flex-col items-center gap-1.5">
                        <File className="h-8 w-8 text-muted-foreground/50" />
                        <span>No class notes handouts processed yet. Click "Add Notes" to chunk them.</span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Right Column: Knowledge chunk preview list */}
              <div className="md:col-span-3 space-y-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Extracted Semantic Knowledge Chunks</h3>
                
                {loadingChunks ? (
                  <div className="py-20 text-center text-muted-foreground text-xs">Loading chunks...</div>
                ) : chunks.length > 0 ? (
                  <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                    {chunks.slice(0, 50).map(chk => (
                      <div key={chk.id} className="p-3 border rounded-xl bg-card shadow-sm hover:border-primary/10 transition-colors">
                        <div className="flex justify-between items-center gap-2 flex-wrap mb-2 text-[10px] font-mono text-muted-foreground">
                          <span>Page {chk.page_number} · Module {chk.module_number || "Unclassified"}</span>
                          <Badge variant="secondary" className="text-[9px] font-sans px-1.5 py-0">
                            {chk.bloom_level || "L2"} • {chk.co_mapping || "CO1"}
                          </Badge>
                        </div>
                        <p className="text-xs text-foreground leading-relaxed font-sans">{chk.chunk_text}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-16 text-center border border-dashed rounded-xl bg-card">
                    <p className="text-xs text-muted-foreground">Upload class notes handouts to preview chunk details here.</p>
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          {/* TAB 3: Question Bank upload and details */}
          <TabsContent value="qbank" className="mt-6 space-y-6 animate-in fade-in-50 duration-200">
            <div className="grid md:grid-cols-5 gap-6">
              {/* Document upload list */}
              <div className="md:col-span-2 space-y-4">
                <Card className="border-border/60 shadow-sm">
                  <CardHeader className="pb-3 flex flex-row items-center justify-between">
                    <div>
                      <CardTitle className="text-base font-semibold">Question Banks</CardTitle>
                      <CardDescription>Verified pools of past questions</CardDescription>
                    </div>
                  </CardHeader>
                  <CardContent className="p-3">
                    {loadingDocs ? (
                      <div className="text-center py-6 text-xs text-muted-foreground">Loading Question Banks...</div>
                    ) : bankDocs.length > 0 ? (
                      <div className="space-y-2">
                        {bankDocs.map(doc => (
                          <div key={doc.id} className="flex items-center justify-between p-3 rounded-lg border border-border/40 hover:bg-muted/15 group transition-colors">
                            <div className="flex items-center gap-2 min-w-0">
                              <FileText className="h-4 w-4 text-amber-500 shrink-0" />
                              <div className="min-w-0">
                                <span className="text-xs font-semibold block truncate text-foreground">{doc.file_name}</span>
                                <span className="text-[10px] text-muted-foreground block">{doc.total_chunks} chunks · processed</span>
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteDoc(doc.id)}
                              className="h-7 w-7 text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-10 text-xs text-muted-foreground flex flex-col items-center gap-1.5">
                        <File className="h-8 w-8 text-muted-foreground/50" />
                        <span>No question banks processed yet. Go to Upload Center to process question banks.</span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Mapped questions list */}
              <div className="md:col-span-3 space-y-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Indexed Question bank</h3>
                
                {loadingQuestions ? (
                  <div className="py-20 text-center text-muted-foreground text-xs">Loading questions...</div>
                ) : questions.length > 0 ? (
                  <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                    {questions.map(q => (
                      <div key={q.id} className="p-3.5 border rounded-xl bg-card shadow-sm hover:border-primary/10 transition-colors">
                        <p className="text-xs font-medium text-foreground leading-relaxed mb-2 font-serif">{q.text}</p>
                        <div className="flex gap-2 flex-wrap text-[10px]">
                          <Badge variant="outline" className="px-1.5 py-0 text-muted-foreground">Module {q.module_number}</Badge>
                          <Badge variant="outline" className="px-1.5 py-0 text-muted-foreground">{q.bloom_level}</Badge>
                          <Badge variant="outline" className="px-1.5 py-0 text-muted-foreground">{q.course_outcome}</Badge>
                          <Badge variant="outline" className="px-1.5 py-0 text-muted-foreground">{q.difficulty}</Badge>
                          <Badge variant="secondary" className="px-1.5 py-0 bg-primary/10 text-primary">{q.marks} Marks</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-16 text-center border border-dashed rounded-xl bg-card">
                    <p className="text-xs text-muted-foreground">No questions cataloged yet.</p>
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          {/* TAB 4: Previous Papers */}
          <TabsContent value="papers" className="mt-6 space-y-6 animate-in fade-in-50 duration-200">
            <div className="grid md:grid-cols-2 gap-6">
              <Card className="border-border/60 shadow-sm">
                <CardHeader>
                  <CardTitle className="text-base font-semibold">Previous Institutional Papers</CardTitle>
                  <CardDescription>Upload past papers to reference and analyze model question sequences</CardDescription>
                </CardHeader>
                <CardContent className="p-3">
                  {loadingDocs ? (
                    <div className="text-center py-6 text-xs text-muted-foreground">Loading Previous Papers...</div>
                  ) : pastDocs.length > 0 ? (
                    <div className="space-y-2">
                      {pastDocs.map(doc => (
                        <div key={doc.id} className="flex items-center justify-between p-3 rounded-lg border border-border/40 hover:bg-muted/15 group transition-colors">
                          <div className="flex items-center gap-2 min-w-0">
                            <FileText className="h-4 w-4 text-emerald-500 shrink-0" />
                            <div className="min-w-0">
                              <span className="text-xs font-semibold block truncate text-foreground">{doc.file_name}</span>
                              <span className="text-[10px] text-muted-foreground block">{doc.total_chunks} chunks · processed</span>
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDeleteDoc(doc.id)}
                            className="h-7 w-7 text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-10 text-xs text-muted-foreground flex flex-col items-center gap-1.5">
                      <File className="h-8 w-8 text-muted-foreground/50" />
                      <span>No past papers processed yet.</span>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* TAB 5: Analytics and syllabus coverage */}
          <TabsContent value="analytics" className="mt-6 space-y-6 animate-in fade-in-50 duration-200">
            {loadingCoverage ? (
              <div className="py-20 text-center text-muted-foreground">Generating topic analytics...</div>
            ) : coverageData ? (
              <div className="grid md:grid-cols-3 gap-6">
                {/* Left panel: Coverage status */}
                <div className="md:col-span-1 space-y-6">
                  <Card className="border-border/60 shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-base font-semibold">Syllabus Indexing Coverage</CardTitle>
                      <CardDescription>Real-time knowledge chunk mapping stats</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6 pt-2">
                      <div className="space-y-2">
                        <div className="flex justify-between items-center text-xs">
                          <span className="font-medium text-muted-foreground">Total Chunks</span>
                          <span className="font-bold text-foreground">{coverageData.total_chunks} Chunks</span>
                        </div>
                        <div className="flex justify-between items-center text-xs">
                          <span className="font-medium text-muted-foreground">Processed Files</span>
                          <span className="font-bold text-foreground">{coverageData.total_documents} Files</span>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="flex justify-between items-center text-xs font-semibold">
                          <span>Syllabus Target Coverage</span>
                          <span className="text-primary">{Math.round((coverageData.coverage?.filter(c => c.chunk_count > 0).length / Math.max(1, coverageData.coverage?.length)) * 100)}%</span>
                        </div>
                        <Progress value={Math.round((coverageData.coverage?.filter(c => c.chunk_count > 0).length / Math.max(1, coverageData.coverage?.length)) * 100)} className="h-2" />
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Right panel: coverage items */}
                <div className="md:col-span-2 space-y-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Syllabus Topic Coverage Mapping</h3>
                  <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                    {coverageData.coverage?.map((item, idx) => (
                      <div key={idx} className="p-3 border rounded-xl bg-card shadow-sm flex items-center justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <span className="text-[10px] font-mono text-muted-foreground block mb-1">Module {item.module_number}</span>
                          <span className="text-xs font-medium text-foreground block truncate">{item.topic_name}</span>
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                          <Badge variant={item.chunk_count > 0 ? "default" : "outline"} className={item.chunk_count > 0 ? "bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20" : "text-amber-600 border-amber-500/30"}>
                            {item.chunk_count > 0 ? `${item.chunk_count} Chunks` : "0 Chunks (Gap)"}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-16 text-center border border-dashed rounded-xl bg-card">
                <p className="text-xs text-muted-foreground">No syllabus loaded to calculate analytics.</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    );
  }

  // Split card category listing
  const semesterCategories = Array.from(new Set(subjects.map(s => s.semester))).sort();

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold font-serif tracking-tight">Subject Workspaces</h1>
          <p className="text-muted-foreground mt-1">
            Manage your courses, syllabi, constraints, and AI generation profiles.
          </p>
        </div>
        
        <Dialog open={isAddOpen} onOpenChange={setIsAddOpen}>
          <DialogTrigger asChild>
            <Button className="hover-elevate">
              <Plus className="mr-2 h-4 w-4" /> Add Subject
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Create New Subject</DialogTitle>
              <DialogDescription>
                Define the primary academic constraints. The syllabus you upload later will form the generation boundary.
              </DialogDescription>
            </DialogHeader>
            
            <form onSubmit={handleSubmit} className="space-y-6 pt-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Subject Name</Label>
                  <Input name="name" placeholder="e.g. Operating Systems" required />
                </div>
                <div className="space-y-2">
                  <Label>Subject Code</Label>
                  <Input name="code" placeholder="e.g. 22CS41" required />
                </div>
                
                <div className="space-y-2">
                  <Label>Department</Label>
                  <Input name="department" placeholder="e.g. Computer Science" required />
                </div>
                <div className="space-y-2">
                  <Label>Semester</Label>
                  <Input name="semester" type="number" min="1" max="8" defaultValue="4" required />
                </div>
                
                <div className="space-y-2">
                  <Label>Academic Year</Label>
                  <Input name="academic_year" placeholder="e.g. 2025-2026" defaultValue="2025-2026" />
                </div>
                <div className="space-y-2">
                  <Label>Regulation Scheme</Label>
                  <Input name="regulation_scheme" placeholder="e.g. 2022 Scheme" defaultValue="2022 Scheme" />
                </div>

                <div className="space-y-2">
                  <Label>Maximum Marks</Label>
                  <Input name="max_marks" type="number" defaultValue="50" required />
                </div>
                <div className="space-y-2">
                  <Label>Credits</Label>
                  <Input name="credits" type="number" defaultValue="3" required />
                </div>

                <div className="space-y-2">
                  <Label>Exam Duration (Minutes)</Label>
                  <Input name="exam_duration" type="number" defaultValue="180" />
                </div>
                <div className="space-y-2">
                  <Label>Number of Modules</Label>
                  <Input name="number_of_modules" type="number" defaultValue="5" required />
                </div>

                <div className="space-y-2">
                  <Label>Theory/Lab Type</Label>
                  <Select name="theory_lab_type" defaultValue="Theory">
                    <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Theory">Theory</SelectItem>
                      <SelectItem value="Lab">Laboratory</SelectItem>
                      <SelectItem value="Integrated">Integrated (Theory + Lab)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                
                <div className="space-y-2">
                  <Label>Pattern Type</Label>
                  <Select name="pattern_type" defaultValue="Autonomous">
                    <SelectTrigger><SelectValue placeholder="Select pattern" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Autonomous">Autonomous</SelectItem>
                      <SelectItem value="VTU">VTU Affiliated</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              
              <DialogFooter>
                <Button variant="outline" type="button" onClick={() => setIsAddOpen(false)}>Cancel</Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "Creating..." : "Create Subject Workspace"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="space-y-8">
        {loadingSubjects ? (
          <div className="py-20 text-center text-muted-foreground text-sm flex flex-col items-center justify-center gap-2">
            <Loader2 className="h-8 w-8 text-primary animate-spin" />
            <span>Loading subjects...</span>
          </div>
        ) : subjects.length === 0 ? (
          <div className="py-20 text-center border border-dashed rounded-2xl p-6 bg-card max-w-xl mx-auto shadow-sm">
            <BookOpen className="h-12 w-10 text-muted-foreground/50 mx-auto mb-3" />
            <h3 className="text-lg font-semibold mb-1 text-foreground">No subjects found</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-xs mx-auto">Create a subject to set up your academic assessment workspace.</p>
            <Button onClick={() => setIsAddOpen(true)}>Add your first subject</Button>
          </div>
        ) : (
          semesterCategories.map((sem) => {
            const semSubjects = subjects.filter(s => s.semester === sem);
            return (
              <div key={sem} className="space-y-4">
                <div className="flex items-center gap-3">
                  <h2 className="text-lg font-bold font-serif text-foreground">Semester {sem}</h2>
                  <div className="h-px bg-border flex-1" />
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {semSubjects.map((sub) => (
                    <Card
                      key={sub.id}
                      onClick={() => {
                        setActiveSubject(sub);
                        setActiveTab("syllabus");
                      }}
                      className="flex flex-col hover:border-primary/50 transition-colors shadow-sm cursor-pointer group"
                    >
                      <CardHeader className="pb-3">
                        <div className="flex justify-between items-start">
                          <div>
                            <CardTitle className="text-xl font-bold group-hover:text-primary transition-colors line-clamp-1">{sub.name}</CardTitle>
                            <CardDescription className="mt-1 font-mono text-xs">{sub.code}</CardDescription>
                          </div>
                          <div className="bg-primary/10 text-primary text-xs font-semibold px-2 py-1 rounded">
                            Sem {sub.semester}
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent className="flex-1">
                        <div className="grid grid-cols-2 gap-y-2 text-sm text-muted-foreground">
                          <div className="flex items-center gap-1.5">
                            <BookOpen className="h-3.5 w-3.5" /> {sub.number_of_modules} Modules
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Clock className="h-3.5 w-3.5" /> {sub.exam_duration} mins
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Settings className="h-3.5 w-3.5" /> {sub.pattern_type}
                          </div>
                          <div className="flex items-center gap-1.5">
                            <BookOpen className="h-3.5 w-3.5" /> {sub.theory_lab_type}
                          </div>
                        </div>
                      </CardContent>
                      <CardFooter className="pt-3 border-t bg-muted/20 flex justify-between gap-2">
                        <Button className="w-full text-xs" size="sm">Open Assessment Workspace</Button>
                      </CardFooter>
                    </Card>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
