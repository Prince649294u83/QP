/**
 * Knowledge Base — Academic intelligence workspace.
 *
 * Browse, search, review, and manage extracted knowledge chunks.
 * Semantic search, module explorer, chunk confidence viewer.
 */
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  BookOpen,
  Filter,
  SlidersHorizontal,
  Eye,
  ChevronDown,
  Layers,
  Brain,
  Target,
  CheckCircle2,
  XCircle,
  Clock,
  FileText,
  X,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  ChunkCard,
  AIConfidenceBadge,
  BloomBadge,
  COBadge,
  ModuleBadge,
  ApprovalBadge,
  AcademicEmptyState,
  CoverageBar,
} from "@/components/academic";
import {
  useKnowledgeChunks,
  useSearchChunks,
  useApproveChunk,
  useEditChunk,
  useTopicCoverage,
  type KnowledgeChunk as KnowledgeChunkType,
  type ChunkApprovalStatus,
} from "@/lib/academic-api";
import { useSubjects } from "@/lib/ai-api";
import { toast } from "sonner";

export default function KnowledgeBase() {
  const { data: subjects } = useSubjects();
  const [subjectId, setSubjectId] = useState<number | undefined>();
  const [moduleFilter, setModuleFilter] = useState<number | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [searchQuery, setSearchQuery] = useState("");
  const [viewChunk, setViewChunk] = useState<KnowledgeChunkType | null>(null);

  const isSearching = searchQuery.length >= 2;

  const { data: chunks, isLoading } = useKnowledgeChunks({
    subjectId,
    moduleNumber: moduleFilter,
    approvalStatus: statusFilter,
    limit: 50,
  });

  const { data: searchResults } = useSearchChunks(searchQuery, subjectId, moduleFilter);
  const { data: coverage } = useTopicCoverage(subjectId ?? 0);

  const approveMutation = useApproveChunk();
  const editMutation = useEditChunk();

  const displayChunks = isSearching ? searchResults?.chunks : chunks;

  const handleApprove = (chunk: KnowledgeChunkType) => {
    approveMutation.mutate(
      { chunkId: chunk.id, status: "approved" as ChunkApprovalStatus },
      { onSuccess: () => toast.success("Chunk approved") }
    );
  };

  const handleReject = (chunk: KnowledgeChunkType) => {
    approveMutation.mutate(
      { chunkId: chunk.id, status: "rejected" as ChunkApprovalStatus },
      { onSuccess: () => toast.success("Chunk rejected") }
    );
  };

  // Stats
  const totalChunks = chunks?.length ?? 0;
  const pendingReview = chunks?.filter((c) => c.approval_status === "pending_review").length ?? 0;
  const approved = chunks?.filter((c) => ["approved", "auto_approved"].includes(c.approval_status)).length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Knowledge Base</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Browse, search, and review AI-extracted academic content
          </p>
        </div>
        <Select
          value={subjectId?.toString() ?? "all"}
          onValueChange={(v) => setSubjectId(v === "all" ? undefined : Number(v))}
        >
          <SelectTrigger className="w-[220px]">
            <SelectValue placeholder="All Subjects" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Subjects</SelectItem>
            {subjects?.map((s: any) => (
              <SelectItem key={s.id} value={s.id.toString()}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-border/60">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <Layers className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="text-2xl font-bold tabular-nums">{totalChunks}</p>
              <p className="text-xs text-muted-foreground">Total Chunks</p>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border/60">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="rounded-lg bg-amber-500/10 p-2.5">
              <Clock className="h-5 w-5 text-amber-600" />
            </div>
            <div>
              <p className="text-2xl font-bold tabular-nums">{pendingReview}</p>
              <p className="text-xs text-muted-foreground">Pending Review</p>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border/60">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="rounded-lg bg-emerald-500/10 p-2.5">
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            </div>
            <div>
              <p className="text-2xl font-bold tabular-nums">{approved}</p>
              <p className="text-xs text-muted-foreground">Approved</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Search & Filters */}
      <Card className="border-border/60">
        <CardContent className="p-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search topics, concepts, or content..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-muted"
                >
                  <X className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              )}
            </div>
            <Select
              value={moduleFilter?.toString() ?? "all"}
              onValueChange={(v) => setModuleFilter(v === "all" ? undefined : Number(v))}
            >
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="All Modules" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Modules</SelectItem>
                {[1, 2, 3, 4, 5].map((m) => (
                  <SelectItem key={m} value={m.toString()}>Module {m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={statusFilter ?? "all"}
              onValueChange={(v) => setStatusFilter(v === "all" ? undefined : v)}
            >
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="All Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="pending_review">Pending Review</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="auto_approved">Auto-Approved</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
                <SelectItem value="edited">Edited</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {isSearching && searchResults && (
            <p className="text-xs text-muted-foreground mt-2">
              Found {searchResults.total} results for "{searchQuery}"
            </p>
          )}
        </CardContent>
      </Card>

      {/* Chunk Grid */}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {isLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 rounded-xl bg-muted animate-pulse" />
          ))
        ) : displayChunks?.length ? (
          displayChunks.map((chunk) => (
            <ChunkCard
              key={chunk.id}
              chunk={chunk}
              onView={() => setViewChunk(chunk)}
              onApprove={() => handleApprove(chunk)}
              onReject={() => handleReject(chunk)}
            />
          ))
        ) : (
          <div className="col-span-full">
            <AcademicEmptyState
              title={isSearching ? "No results found" : "No knowledge chunks yet"}
              description={
                isSearching
                  ? "Try a different search query or adjust filters"
                  : "Upload academic materials to start building your knowledge base"
              }
              icon={isSearching ? Search : BookOpen}
            />
          </div>
        )}
      </div>

      {/* Chunk Detail Dialog */}
      <ChunkDetailDialog
        chunk={viewChunk}
        open={!!viewChunk}
        onClose={() => setViewChunk(null)}
        onApprove={() => viewChunk && handleApprove(viewChunk)}
        onReject={() => viewChunk && handleReject(viewChunk)}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Chunk Detail Dialog                                                */
/* ------------------------------------------------------------------ */

function ChunkDetailDialog({
  chunk,
  open,
  onClose,
  onApprove,
  onReject,
}: {
  chunk: KnowledgeChunkType | null;
  open: boolean;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  if (!chunk) return null;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg">
            <Eye className="h-5 w-5 text-primary" />
            Chunk Detail
          </DialogTitle>
          <DialogDescription>Review AI-extracted content and metadata</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Metadata badges */}
          <div className="flex flex-wrap gap-2">
            <ModuleBadge module={chunk.module_number} />
            <BloomBadge level={chunk.bloom_level} />
            <COBadge co={chunk.co_mapping} />
            <ApprovalBadge status={chunk.approval_status} />
            <AIConfidenceBadge score={chunk.confidence_score} size="md" />
          </div>

          {/* Topic */}
          {chunk.topic_name && (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Topic</p>
              <p className="text-sm font-semibold text-foreground">{chunk.topic_name}</p>
            </div>
          )}

          <Separator />

          {/* Full text */}
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Extracted Content</p>
            <div className="rounded-lg bg-muted/50 border border-border/40 p-4">
              <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">{chunk.chunk_text}</p>
            </div>
          </div>

          {/* Provenance */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Token Count</p>
              <p className="font-medium tabular-nums">{chunk.token_count}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Chunk Index</p>
              <p className="font-medium tabular-nums">#{chunk.chunk_index + 1}</p>
            </div>
            {chunk.page_number != null && (
              <div>
                <p className="text-xs text-muted-foreground">Page Number</p>
                <p className="font-medium tabular-nums">{chunk.page_number}</p>
              </div>
            )}
            <div>
              <p className="text-xs text-muted-foreground">Document ID</p>
              <p className="font-medium tabular-nums">{chunk.document_id}</p>
            </div>
          </div>

          {/* Actions */}
          {chunk.approval_status === "pending_review" && (
            <>
              <Separator />
              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={onReject} className="text-red-600 border-red-200 hover:bg-red-50">
                  <ThumbsDown className="h-4 w-4 mr-2" />
                  Reject
                </Button>
                <Button onClick={onApprove}>
                  <ThumbsUp className="h-4 w-4 mr-2" />
                  Approve
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
