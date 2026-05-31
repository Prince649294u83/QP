import { useState, useMemo } from "react";
import { Plus, Search, Trash2, Upload, Brain, Loader2, FileText, BarChart3, Layers, Grid3X3, List, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  useListQuestionsApiV1QuestionsGet, 
  useSubjectsApiV1SubjectsGet, 
  useAddQuestionApiV1QuestionsPost, 
  useRemoveQuestionApiV1QuestionsQuestionIdDelete,
  getListQuestionsApiV1QuestionsGetQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAIPrintQuestionBank, useQuestionBankSummary } from "@/lib/ai-api";

interface QuestionStats {
  total: number;
  bySubject: Record<string, number>;
  byModule: Record<number, number>;
  byRBT: Record<string, number>;
  byCO: Record<string, number>;
  byDifficulty: Record<string, number>;
  verified: number;
  pending: number;
}

export default function Questions() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("all");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("all");
  const [selectedModule, setSelectedModule] = useState("all");
  const [selectedBloom, setSelectedBloom] = useState("all");
  const [selectedDifficulty, setSelectedDifficulty] = useState("all");
  const [selectedCO, setSelectedCO] = useState("all");
  const [uploadSubject, setUploadSubject] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  
  const [newQuestion, setNewQuestion] = useState({
    text: "",
    subject_id: "",
    course_outcome: "CO1",
    bloom_level: "L1",
    difficulty: "Easy",
    marks: 5,
    module_number: 1
  });

  const { data: subjects = [] } = useSubjectsApiV1SubjectsGet();

  const { data: questions = [], isLoading: isLoadingQuestions } = useListQuestionsApiV1QuestionsGet({
    search: search || undefined,
    bloom_level: selectedBloom !== "all" ? selectedBloom : undefined,
    difficulty: selectedDifficulty !== "all" ? selectedDifficulty : undefined,
  });
  const { data: bankSummary } = useQuestionBankSummary(
    selectedSubject !== "all" ? parseInt(selectedSubject) : undefined,
  );

  const aiUploadMutation = useAIPrintQuestionBank();

  const stats: QuestionStats = useMemo(() => {
    const result: QuestionStats = {
      total: questions.length,
      bySubject: {},
      byModule: {},
      byRBT: {},
      byCO: {},
      byDifficulty: {},
      verified: 0,
      pending: 0
    };

    questions.forEach((q: any) => {
      result.bySubject[q.subject_id] = (result.bySubject[q.subject_id] || 0) + 1;
      result.byModule[q.module_number || 1] = (result.byModule[q.module_number || 1] || 0) + 1;
      result.byRBT[q.bloom_level] = (result.byRBT[q.bloom_level] || 0) + 1;
      result.byCO[q.course_outcome] = (result.byCO[q.course_outcome] || 0) + 1;
      result.byDifficulty[q.difficulty] = (result.byDifficulty[q.difficulty] || 0) + 1;
      
      if (q.is_verified) result.verified++;
      else result.pending++;
    });

    return result;
  }, [questions]);

  const filteredQuestions = useMemo(() => {
    return questions.filter((q: any) => {
      if (selectedSubject !== "all" && q.subject_id !== parseInt(selectedSubject)) return false;
      if (selectedModule !== "all" && (q.module_number || 1) !== parseInt(selectedModule)) return false;
      if (selectedCO !== "all" && q.course_outcome !== selectedCO) return false;
      return true;
    });
  }, [questions, selectedSubject, selectedModule, selectedCO]);

  const handleAIPrint = async () => {
    if (!uploadFile || !uploadSubject) {
      toast.error("Please select a file and subject");
      return;
    }

    setUploadProgress(10);
    try {
      const result = await aiUploadMutation.mutateAsync({
        subject_id: parseInt(uploadSubject),
        file: uploadFile,
      });

      setUploadProgress(100);
      
      if (result.success) {
        toast.success(`Success! Extracted ${result.total_extracted} questions (${result.auto_approved} auto-approved)`);
        queryClient.invalidateQueries({ queryKey: getListQuestionsApiV1QuestionsGetQueryKey() });
        setIsUploadModalOpen(false);
        setUploadFile(null);
        setUploadSubject("");
      } else {
        toast.error(result.error || "AI processing failed");
      }
    } catch (err: any) {
      toast.error(err.message || "Upload failed");
    } finally {
      setUploadProgress(0);
    }
  };

  const addQuestionMutation = useAddQuestionApiV1QuestionsPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListQuestionsApiV1QuestionsGetQueryKey() });
        setIsAddModalOpen(false);
        setNewQuestion({
          text: "",
          subject_id: "",
          course_outcome: "CO1",
          bloom_level: "L1",
          difficulty: "Easy",
          marks: 5,
          module_number: 1
        });
        toast.success("Question added successfully");
      },
      onError: (err: any) => toast.error(`Failed to add question: ${err.message}`)
    }
  });

  const deleteQuestionMutation = useRemoveQuestionApiV1QuestionsQuestionIdDelete({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListQuestionsApiV1QuestionsGetQueryKey() });
        toast.success("Question deleted successfully");
      },
      onError: () => {
        toast.error("Failed to delete question");
      }
    }
  });

  const handleAddQuestion = () => {
    if (!newQuestion.text || !newQuestion.subject_id) {
      toast.error("Please enter question text and select a subject");
      return;
    }

    addQuestionMutation.mutate({
      data: {
        subject_id: parseInt(newQuestion.subject_id),
        text: newQuestion.text,
        course_outcome: newQuestion.course_outcome,
        bloom_level: newQuestion.bloom_level,
        difficulty: newQuestion.difficulty.toLowerCase(),
        marks: newQuestion.marks,
        module_number: newQuestion.module_number,
        tags: []
      }
    });
  };

  const getBloomBadgeColor = (level: string) => {
    const colors: Record<string, string> = {
      L1: "bg-green-100 text-green-800",
      L2: "bg-blue-100 text-blue-800",
      L3: "bg-yellow-100 text-yellow-800",
      L4: "bg-orange-100 text-orange-800",
      L5: "bg-red-100 text-red-800",
      L6: "bg-purple-100 text-purple-800",
    };
    return colors[level] || "bg-gray-100";
  };

  const getDifficultyBadgeColor = (diff: string) => {
    const colors: Record<string, string> = {
      easy: "bg-green-100 text-green-800",
      medium: "bg-yellow-100 text-yellow-800",
      hard: "bg-red-100 text-red-800",
    };
    return colors[diff] || "bg-gray-100";
  };

  const StatCard = ({ title, value, icon: Icon, color }: { title: string; value: number; icon: any; color: string }) => (
    <Card className="flex items-center p-4">
      <div className={`p-3 rounded-lg ${color}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="ml-4">
        <p className="text-sm text-muted-foreground">{title}</p>
        <p className="text-2xl font-bold">{value}</p>
      </div>
    </Card>
  );

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-foreground font-serif">Question Bank</h1>
          <p className="text-muted-foreground">Complete repository of all questions in the database</p>
        </div>
        <div className="flex gap-2">
          <Dialog open={isUploadModalOpen} onOpenChange={setIsUploadModalOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="gap-2">
                <Brain className="h-4 w-4" />
                AI Upload
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Brain className="h-5 w-5" />
                  AI-Powered Question Extraction
                </DialogTitle>
                <DialogDescription>
                  Upload question bank and AI will extract & classify all questions.
                </DialogDescription>
              </DialogHeader>
              
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label>Select Subject</Label>
                  <Select value={uploadSubject} onValueChange={setUploadSubject}>
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a subject" />
                    </SelectTrigger>
                    <SelectContent>
                      {subjects.map((s: any) => (
                        <SelectItem key={s.id} value={s.id.toString()}>
                          {s.name} ({s.code})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Upload Question Bank</Label>
                  <div className="border-2 border-dashed rounded-lg p-6 text-center hover:bg-muted/50 transition-colors cursor-pointer">
                    <input
                      type="file"
                      accept=".pdf,.docx,.doc,.png,.jpg,.jpeg"
                      className="hidden"
                      id="file-upload"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                    />
                    <label htmlFor="file-upload" className="cursor-pointer">
                      {uploadFile ? (
                        <div className="flex items-center justify-center gap-2">
                          <FileText className="h-8 w-8 text-primary" />
                          <span className="font-medium">{uploadFile.name}</span>
                        </div>
                      ) : (
                        <>
                          <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                          <p className="text-sm text-muted-foreground">Click to upload</p>
                        </>
                      )}
                    </label>
                  </div>
                </div>

                {aiUploadMutation.isPending && (
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span>Processing with Llama 3.2 Vision...</span>
                      <span>{uploadProgress}%</span>
                    </div>
                    <Progress value={uploadProgress} className="h-2" />
                  </div>
                )}
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setIsUploadModalOpen(false)}>Cancel</Button>
                <Button 
                  onClick={handleAIPrint} 
                  disabled={!uploadFile || !uploadSubject || aiUploadMutation.isPending}
                  className="gap-2"
                >
                  {aiUploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
                  Extract with AI
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={isAddModalOpen} onOpenChange={setIsAddModalOpen}>
            <DialogTrigger asChild>
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Add Question
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>Add New Question</DialogTitle>
                <DialogDescription>Manually add a question to the database.</DialogDescription>
              </DialogHeader>
              
              <div className="grid gap-4 py-4">
                <div className="space-y-2">
                  <Label>Subject</Label>
                  <Select value={newQuestion.subject_id} onValueChange={(v) => setNewQuestion({...newQuestion, subject_id: v})}>
                    <SelectTrigger><SelectValue placeholder="Select subject" /></SelectTrigger>
                    <SelectContent>
                      {subjects.map((s: any) => (
                        <SelectItem key={s.id} value={s.id.toString()}>{s.name} ({s.code})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Question Text</Label>
                  <Textarea value={newQuestion.text} onChange={(e) => setNewQuestion({...newQuestion, text: e.target.value})} placeholder="Enter question..." rows={3} />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Marks</Label>
                    <Select value={newQuestion.marks.toString()} onValueChange={(v) => setNewQuestion({...newQuestion, marks: parseInt(v)})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="5">5 Marks</SelectItem>
                        <SelectItem value="10">10 Marks</SelectItem>
                        <SelectItem value="15">15 Marks</SelectItem>
                        <SelectItem value="20">20 Marks</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Module</Label>
                    <Select value={newQuestion.module_number.toString()} onValueChange={(v) => setNewQuestion({...newQuestion, module_number: parseInt(v)})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {[1,2,3,4,5].map(m => <SelectItem key={m} value={m.toString()}>Module {m}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label>Bloom Level</Label>
                    <Select value={newQuestion.bloom_level} onValueChange={(v) => setNewQuestion({...newQuestion, bloom_level: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {["L1","L2","L3","L4","L5","L6"].map(l => <SelectItem key={l} value={l}>{l}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Course Outcome</Label>
                    <Select value={newQuestion.course_outcome} onValueChange={(v) => setNewQuestion({...newQuestion, course_outcome: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {["CO1","CO2","CO3","CO4","CO5","CO6"].map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Difficulty</Label>
                    <Select value={newQuestion.difficulty} onValueChange={(v) => setNewQuestion({...newQuestion, difficulty: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Easy">Easy</SelectItem>
                        <SelectItem value="Medium">Medium</SelectItem>
                        <SelectItem value="Hard">Hard</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setIsAddModalOpen(false)}>Cancel</Button>
                <Button onClick={handleAddQuestion} disabled={addQuestionMutation.isPending}>
                  {addQuestionMutation.isPending ? "Adding..." : "Add Question"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Statistics Dashboard */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <StatCard title="Total Questions" value={stats.total} icon={FileText} color="bg-blue-100 text-blue-600" />
        <StatCard title="Source Files" value={bankSummary?.total_documents || 0} icon={Upload} color="bg-slate-100 text-slate-700" />
        <StatCard title="Verified" value={stats.verified} icon={Check} color="bg-green-100 text-green-600" />
        <StatCard title="Pending Review" value={stats.pending} icon={Loader2} color="bg-yellow-100 text-yellow-600" />
        <StatCard title="By Module 1" value={stats.byModule[1] || 0} icon={Layers} color="bg-purple-100 text-purple-600" />
        <StatCard title="By Module 2" value={stats.byModule[2] || 0} icon={Layers} color="bg-indigo-100 text-indigo-600" />
        <StatCard title="By Module 3" value={stats.byModule[3] || 0} icon={Layers} color="bg-pink-100 text-pink-600" />
      </div>

      {bankSummary && (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Card>
            <CardHeader>
              <CardTitle>AI Index Status</CardTitle>
              <CardDescription>
                The retrieval layer is ready for {bankSummary.retrieval_ready_questions} indexed questions.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border bg-muted/20 p-4">
                <p className="text-2xl font-bold">{bankSummary.total_documents}</p>
                <p className="text-sm text-muted-foreground">Documents processed</p>
              </div>
              <div className="rounded-lg border bg-muted/20 p-4">
                <p className="text-2xl font-bold">{bankSummary.verified_questions}</p>
                <p className="text-sm text-muted-foreground">Verified questions</p>
              </div>
              <div className="rounded-lg border bg-muted/20 p-4">
                <p className="text-2xl font-bold">{bankSummary.pending_questions}</p>
                <p className="text-sm text-muted-foreground">Awaiting review</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Coverage Watchlist</CardTitle>
              <CardDescription>Quick gaps the faculty team may want to close.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {bankSummary.gaps.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No major gaps detected for the current filter.
                </p>
              ) : (
                bankSummary.gaps.slice(0, 4).map((gap) => (
                  <div key={gap} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    {gap}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Tabs defaultValue="all" onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4 lg:w-[600px]">
          <TabsTrigger value="all" className="gap-2">
            <List className="h-4 w-4" />
            All Questions
          </TabsTrigger>
          <TabsTrigger value="bysubject" className="gap-2">
            <Grid3X3 className="h-4 w-4" />
            By Subject
          </TabsTrigger>
          <TabsTrigger value="bymodule" className="gap-2">
            <Layers className="h-4 w-4" />
            By Module
          </TabsTrigger>
          <TabsTrigger value="analytics" className="gap-2">
            <BarChart3 className="h-4 w-4" />
            Analytics
          </TabsTrigger>
        </TabsList>

        <TabsContent value="all" className="space-y-4 mt-4">
          <Card>
            <CardHeader className="pb-4">
              <div className="flex flex-col sm:flex-row gap-4 justify-between">
                <div className="relative flex-1 max-w-md">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input placeholder="Search questions..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-10" />
                </div>
                <div className="flex gap-2 flex-wrap">
                  <Select value={selectedSubject} onValueChange={setSelectedSubject}>
                    <SelectTrigger className="w-36"><SelectValue placeholder="Subject" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Subjects</SelectItem>
                      {subjects.map((s: any) => <SelectItem key={s.id} value={s.id.toString()}>{s.code}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={selectedModule} onValueChange={setSelectedModule}>
                    <SelectTrigger className="w-28"><SelectValue placeholder="Module" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Modules</SelectItem>
                      {[1,2,3,4,5].map(m => <SelectItem key={m} value={m.toString()}>Module {m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={selectedBloom} onValueChange={setSelectedBloom}>
                    <SelectTrigger className="w-28"><SelectValue placeholder="RBT" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All RBT</SelectItem>
                      {["L1","L2","L3","L4","L5","L6"].map(l => <SelectItem key={l} value={l}>{l}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={selectedDifficulty} onValueChange={setSelectedDifficulty}>
                    <SelectTrigger className="w-32"><SelectValue placeholder="Difficulty" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Levels</SelectItem>
                      <SelectItem value="easy">Easy</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="hard">Hard</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={selectedCO} onValueChange={setSelectedCO}>
                    <SelectTrigger className="w-28"><SelectValue placeholder="CO" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All COs</SelectItem>
                      {["CO1","CO2","CO3","CO4","CO5","CO6"].map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="text-sm text-muted-foreground">
                Showing {filteredQuestions.length} of {stats.total} questions
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">#</TableHead>
                    <TableHead>Question</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Module</TableHead>
                    <TableHead>Marks</TableHead>
                    <TableHead>RBT</TableHead>
                    <TableHead>CO</TableHead>
                    <TableHead>Difficulty</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-16">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoadingQuestions ? (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center py-8 text-muted-foreground">Loading...</TableCell>
                    </TableRow>
                  ) : filteredQuestions.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center py-8 text-muted-foreground">
                        No questions found. Upload a question bank or add manually.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredQuestions.map((q: any, idx: number) => (
                      <TableRow key={q.id}>
                        <TableCell className="font-medium">{idx + 1}</TableCell>
                        <TableCell className="max-w-md">
                          <p className="truncate" title={q.text}>{q.text}</p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{subjects.find((s: any) => s.id === q.subject_id)?.code || q.subject_id}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">M{q.module_number || 1}</Badge>
                        </TableCell>
                        <TableCell>{q.marks}</TableCell>
                        <TableCell>
                          <Badge className={getBloomBadgeColor(q.bloom_level)}>{q.bloom_level}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{q.course_outcome}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge className={getDifficultyBadgeColor(q.difficulty)}>{q.difficulty}</Badge>
                        </TableCell>
                        <TableCell>
                          {q.is_verified ? (
                            <Badge className="bg-green-100 text-green-800">Verified</Badge>
                          ) : (
                            <Badge className="bg-yellow-100 text-yellow-800">Pending</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => deleteQuestionMutation.mutate(q.id)}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bysubject" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(stats.bySubject).map(([subjectId, count]: [string, any]) => {
              const subject = subjects.find((s: any) => s.id === parseInt(subjectId));
              return (
                <Card key={subjectId} className="hover:shadow-md transition-shadow cursor-pointer">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-lg">{subject?.name || `Subject ${subjectId}`}</CardTitle>
                    <CardDescription>{subject?.code || `ID: ${subjectId}`}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center justify-between">
                      <span className="text-3xl font-bold">{count}</span>
                      <span className="text-muted-foreground">questions</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </TabsContent>

        <TabsContent value="bymodule" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            {[1,2,3,4,5].map(module => (
              <Card key={module} className="hover:shadow-md transition-shadow">
                <CardHeader className="pb-2">
                  <CardTitle className="text-lg">Module {module}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center justify-between">
                    <span className="text-3xl font-bold">{stats.byModule[module] || 0}</span>
                    <span className="text-muted-foreground">questions</span>
                  </div>
                  <Progress value={((stats.byModule[module] || 0) / stats.total) * 100} className="mt-2" />
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="analytics" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>RBT Level Distribution</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {["L1","L2","L3","L4","L5","L6"].map(rbt => (
                  <div key={rbt} className="flex items-center justify-between">
                    <span className="font-medium">{rbt}</span>
                    <div className="flex items-center gap-2">
                      <Progress value={(stats.byRBT[rbt] || 0) / stats.total * 100} className="w-32" />
                      <span className="text-sm text-muted-foreground w-8">{stats.byRBT[rbt] || 0}</span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Course Outcome Distribution</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {["CO1","CO2","CO3","CO4","CO5","CO6"].map(co => (
                  <div key={co} className="flex items-center justify-between">
                    <span className="font-medium">{co}</span>
                    <div className="flex items-center gap-2">
                      <Progress value={(stats.byCO[co] || 0) / stats.total * 100} className="w-32" />
                      <span className="text-sm text-muted-foreground w-8">{stats.byCO[co] || 0}</span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Difficulty Distribution</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {["easy", "medium", "hard"].map(diff => (
                  <div key={diff} className="flex items-center justify-between">
                    <span className="font-medium capitalize">{diff}</span>
                    <div className="flex items-center gap-2">
                      <Progress value={(stats.byDifficulty[diff] || 0) / stats.total * 100} className="w-32" />
                      <span className="text-sm text-muted-foreground w-8">{stats.byDifficulty[diff] || 0}</span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Verification Status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium">Verified</span>
                  <div className="flex items-center gap-2">
                    <Progress value={stats.verified / stats.total * 100} className="w-32" />
                    <span className="text-sm text-muted-foreground w-8">{stats.verified}</span>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="font-medium">Pending Review</span>
                  <div className="flex items-center gap-2">
                    <Progress value={stats.pending / stats.total * 100} className="w-32" />
                    <span className="text-sm text-muted-foreground w-8">{stats.pending}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Check(props: any) {
  return (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
