import { useState } from "react";
import { CheckCircle, XCircle, Eye, Calendar, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { PaperPreview } from "@/components/paper-preview";
import { 
  usePendingReviewsApiV1ReviewsPendingGet, 
  useTakeReviewActionApiV1ReviewsPaperIdActionPost,
  useSubjectsApiV1SubjectsGet,
  getPendingReviewsApiV1ReviewsPendingGetQueryKey
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";

export default function Review() {
  const queryClient = useQueryClient();
  const [selectedPaper, setSelectedPaper] = useState<any>(null);
  const [reviewAction, setReviewAction] = useState<{ id: number, type: 'approve' | 'reject' } | null>(null);
  const [comments, setComments] = useState("");

  const { data: papers = [], isLoading } = usePendingReviewsApiV1ReviewsPendingGet();
  const { data: subjects = [] } = useSubjectsApiV1SubjectsGet();

  const takeActionMutation = useTakeReviewActionApiV1ReviewsPaperIdActionPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getPendingReviewsApiV1ReviewsPendingGetQueryKey() });
        toast.success(`Paper ${reviewAction?.type === 'approve' ? 'approved' : 'rejected'} successfully`);
        setReviewAction(null);
        setComments("");
        setSelectedPaper(null);
      },
      onError: (err: any) => {
        toast.error(`Action failed: ${err.response?.data?.detail || err.message}`);
      }
    }
  });

  const getSubjectName = (subjectId: number) => {
    return subjects.find(s => s.id === subjectId)?.name || `Subject ${subjectId}`;
  };

  const handleAction = () => {
    if (!reviewAction) return;
    if (comments.length < 3) {
      toast.error("Please provide a comment (min 3 chars)");
      return;
    }

    takeActionMutation.mutate({
      paperId: reviewAction.id,
      data: {
        decision: reviewAction.type === 'approve' ? 'approved' : 'rejected',
        comments: comments
      } as any
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground font-serif tracking-tight">Pending Reviews</h1>
        <p className="text-muted-foreground">Review and approve question papers submitted by faculty.</p>
      </div>

      <div className="bg-card border rounded-lg shadow-sm overflow-hidden">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>Paper ID</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Faculty</TableHead>
              <TableHead>Exam Type</TableHead>
              <TableHead>Submitted On</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  Loading pending reviews...
                </TableCell>
              </TableRow>
            ) : papers.length > 0 ? (
              papers.map((paper) => (
                <TableRow key={paper.id}>
                  <TableCell className="font-medium font-mono text-xs">#{paper.id}</TableCell>
                  <TableCell>{getSubjectName(paper.subject_id)}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <User className="h-3 w-3 text-muted-foreground" />
                      <span className="text-sm">Faculty Member</span>
                    </div>
                  </TableCell>
                  <TableCell>{paper.exam_type}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                      <Calendar className="h-3 w-3" />
                      {paper.submitted_at ? format(new Date(paper.submitted_at), "MMM d, HH:mm") : "N/A"}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="ghost" size="sm" className="hover:text-primary" onClick={() => setSelectedPaper(paper)}>
                        <Eye className="mr-1 h-4 w-4" /> Preview
                      </Button>
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        className="h-8 w-8 text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50" 
                        onClick={() => setReviewAction({ id: paper.id, type: 'approve' })}
                      >
                        <CheckCircle className="h-4 w-4" />
                      </Button>
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        className="h-8 w-8 text-red-600 hover:text-red-700 hover:bg-red-50" 
                        onClick={() => setReviewAction({ id: paper.id, type: 'reject' })}
                      >
                        <XCircle className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  No papers pending review.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Review Dialog */}
      <Dialog open={!!reviewAction} onOpenChange={(open) => !open && setReviewAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {reviewAction?.type === 'approve' ? 'Approve' : 'Reject'} Question Paper
            </DialogTitle>
            <DialogDescription>
              Please provide comments for the faculty member.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Textarea 
              placeholder="Enter your review comments here..." 
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              className="min-h-[100px]"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReviewAction(null)}>Cancel</Button>
            <Button 
              variant={reviewAction?.type === 'approve' ? 'default' : 'destructive'}
              onClick={handleAction}
              disabled={takeActionMutation.isPending}
            >
              {takeActionMutation.isPending ? "Processing..." : `Confirm ${reviewAction?.type === 'approve' ? 'Approval' : 'Rejection'}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={!!selectedPaper} onOpenChange={(open) => !open && setSelectedPaper(null)}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-0">
          <DialogHeader className="p-6 border-b pb-4">
            <div className="flex items-center justify-between pr-8">
              <DialogTitle className="text-xl">Review: {selectedPaper?.title}</DialogTitle>
              <DialogDescription>
                Inspect the submitted paper before approving or rejecting it.
              </DialogDescription>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="text-red-600 border-red-200 hover:bg-red-50" onClick={() => setReviewAction({ id: selectedPaper.id, type: 'reject' })}>
                  Reject
                </Button>
                <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => setReviewAction({ id: selectedPaper.id, type: 'approve' })}>
                  Approve
                </Button>
              </div>
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
