import { useState } from "react";
import { Eye, Download, Trash2, Calendar, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { PaperPreview } from "@/components/paper-preview";
import { 
  useListPapersApiV1PapersGet, 
  useRemovePaperApiV1PapersPaperIdDelete, 
  useSubjectsApiV1SubjectsGet,
  getListPapersApiV1PapersGetQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { exportToDocx } from "@/utils/docxExport";

export default function History() {
  const queryClient = useQueryClient();
  const [selectedPaper, setSelectedPaper] = useState<any>(null);

  const { data: papers = [], isLoading } = useListPapersApiV1PapersGet();
  const { data: subjects = [] } = useSubjectsApiV1SubjectsGet();

  const deletePaperMutation = useRemovePaperApiV1PapersPaperIdDelete({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListPapersApiV1PapersGetQueryKey() });
        toast.success("Paper deleted successfully");
      },
      onError: () => {
        toast.error("Failed to delete paper");
      }
    }
  });

  const getSubjectName = (subjectId: number) => {
    return subjects.find(s => s.id === subjectId)?.name || `Subject ${subjectId}`;
  };

  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this paper?")) {
      deletePaperMutation.mutate({ paperId: id });
    }
  };

  const handleDownload = async (paper: any) => {
    try {
      await exportToDocx(paper);
      toast.success("Paper downloaded successfully!");
    } catch (error) {
      toast.error("Failed to download paper");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground font-serif tracking-tight">Generated Papers</h1>
        <p className="text-muted-foreground">View and manage previously generated question papers.</p>
      </div>

      <div className="bg-card border rounded-lg shadow-sm overflow-hidden">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>Paper ID</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Exam Type</TableHead>
              <TableHead>Semester</TableHead>
              <TableHead>Generated On</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  Loading generated papers...
                </TableCell>
              </TableRow>
            ) : papers.length > 0 ? (
              papers.map((paper) => (
                <TableRow key={paper.id}>
                  <TableCell className="font-medium font-mono text-xs">#{paper.id}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary opacity-70" />
                      {getSubjectName(paper.subject_id)}
                    </div>
                  </TableCell>
                  <TableCell>{paper.exam_type}</TableCell>
                  <TableCell>{paper.semester}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                      <Calendar className="h-3 w-3" />
                      {format(new Date(paper.created_at), "MMM d, yyyy")}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={paper.status === 'approved' ? 'default' : 'secondary'} className="font-normal capitalize">
                      {paper.status.replace("_", " ")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="ghost" size="icon" className="h-8 w-8 hover:text-primary" onClick={() => setSelectedPaper(paper)}>
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8 hover:text-primary" onClick={() => handleDownload(paper)}>
                        <Download className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={() => handleDelete(paper.id)} disabled={deletePaperMutation.isPending}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  No generated papers found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!selectedPaper} onOpenChange={(open) => !open && setSelectedPaper(null)}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-0">
          <DialogHeader className="p-6 border-b pb-4">
            <div className="flex items-center justify-between pr-8">
              <div>
                <DialogTitle className="text-xl">{selectedPaper?.title}</DialogTitle>
                <DialogDescription>
                  Preview the generated paper and download it as a DOCX file.
                </DialogDescription>
                <p className="text-sm text-muted-foreground mt-1">Generated on {selectedPaper?.created_at ? format(new Date(selectedPaper.created_at), "PPP") : ""}</p>
              </div>
              <Button size="sm" onClick={() => selectedPaper && handleDownload(selectedPaper)}>
                <Download className="mr-2 h-4 w-4" /> Download .docx
              </Button>
            </div>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto p-6 bg-muted/30">
            <div className="bg-white p-8 shadow-sm border max-w-3xl mx-auto">
              <PaperPreview 
                formData={{
                  subjectName: getSubjectName(selectedPaper?.subject_id),
                  subjectCode: selectedPaper?.subject_code,
                  department: selectedPaper?.department_name,
                  examType: selectedPaper?.exam_type,
                  semester: selectedPaper?.semester
                }} 
                questions={selectedPaper?.questions || []}
                generatedPaper={selectedPaper}
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
