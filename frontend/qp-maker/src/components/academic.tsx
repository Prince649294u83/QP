/**
 * Reusable academic UI components for the Knowledge Intelligence Layer.
 *
 * - AIConfidenceBadge
 * - ProcessingTimeline
 * - BloomBadge
 * - COBadge
 * - ChunkCard
 * - SourceTraceCard
 * - CoverageBar
 */
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  AlertTriangle,
  XCircle,
  Sparkles,
  BookOpen,
  Target,
  ShieldCheck,
  Eye,
  Edit3,
  ThumbsUp,
  ThumbsDown,
  Layers,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ProcessingStatus, ChunkApprovalStatus, KnowledgeChunk } from "@/lib/academic-api";

/* ------------------------------------------------------------------ */
/*  AI Confidence Badge                                                */
/* ------------------------------------------------------------------ */

const confidenceMeta = (score: number) => {
  if (score >= 0.8) return { label: "High", color: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/25", icon: ShieldCheck };
  if (score >= 0.5) return { label: "Medium", color: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/25", icon: AlertTriangle };
  return { label: "Low", color: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/25", icon: XCircle };
};

export function AIConfidenceBadge({ score, showLabel = true, size = "sm" }: {
  score: number;
  showLabel?: boolean;
  size?: "sm" | "md";
}) {
  const meta = confidenceMeta(score);
  const Icon = meta.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn(
          "inline-flex items-center gap-1 rounded-full border font-medium",
          meta.color,
          size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-xs"
        )}>
          <Icon className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} />
          {showLabel && <span>{meta.label}</span>}
          <span className="tabular-nums">{Math.round(score * 100)}%</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p className="text-xs">AI Confidence: {(score * 100).toFixed(1)}%</p>
        <p className="text-[10px] text-muted-foreground mt-0.5">{meta.label} reliability — always verify critical content</p>
      </TooltipContent>
    </Tooltip>
  );
}

/* ------------------------------------------------------------------ */
/*  Bloom Level Badge                                                  */
/* ------------------------------------------------------------------ */

const BLOOM_COLORS: Record<string, string> = {
  L1: "bg-sky-500/15 text-sky-700 dark:text-sky-400 border-sky-500/25",
  L2: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/25",
  L3: "bg-violet-500/15 text-violet-700 dark:text-violet-400 border-violet-500/25",
  L4: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/25",
  L5: "bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/25",
  L6: "bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/25",
};

const BLOOM_NAMES: Record<string, string> = {
  L1: "Remember", L2: "Understand", L3: "Apply",
  L4: "Analyze", L5: "Evaluate", L6: "Create",
};

export function BloomBadge({ level }: { level: string | null }) {
  if (!level) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold", BLOOM_COLORS[level] ?? "bg-muted text-muted-foreground border-border")}>
          <Brain className="h-3 w-3" />
          {level}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs font-medium">{level} — {BLOOM_NAMES[level] ?? "Unknown"}</p>
        <p className="text-[10px] text-muted-foreground">Bloom's Taxonomy Level</p>
      </TooltipContent>
    </Tooltip>
  );
}

/* ------------------------------------------------------------------ */
/*  CO Badge                                                           */
/* ------------------------------------------------------------------ */

export function COBadge({ co }: { co: string | null }) {
  if (!co) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
      <Target className="h-3 w-3" />
      {co}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Module Badge                                                       */
/* ------------------------------------------------------------------ */

export function ModuleBadge({ module }: { module: number | null }) {
  if (module == null) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:text-indigo-400">
      <BookOpen className="h-3 w-3" />
      M{module}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Approval Status Badge                                              */
/* ------------------------------------------------------------------ */

const APPROVAL_META: Record<ChunkApprovalStatus, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  auto_approved: { label: "Auto-Approved", color: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/25", icon: Sparkles },
  pending_review: { label: "Pending Review", color: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/25", icon: Clock },
  approved: { label: "Approved", color: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/25", icon: CheckCircle2 },
  rejected: { label: "Rejected", color: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/25", icon: XCircle },
  edited: { label: "Edited", color: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/25", icon: Edit3 },
};

export function ApprovalBadge({ status }: { status: ChunkApprovalStatus }) {
  const meta = APPROVAL_META[status];
  const Icon = meta.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium", meta.color)}>
      <Icon className="h-3 w-3" />
      {meta.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Processing Timeline                                                */
/* ------------------------------------------------------------------ */

const PIPELINE_STAGES: { key: ProcessingStatus; label: string; icon: typeof FileText }[] = [
  { key: "pending", label: "Queued", icon: Clock },
  { key: "extracting", label: "Extracting", icon: FileText },
  { key: "chunking", label: "Chunking", icon: Layers },
  { key: "embedding", label: "Embedding", icon: Brain },
  { key: "completed", label: "Ready", icon: CheckCircle2 },
];

export function ProcessingTimeline({ status }: { status: ProcessingStatus }) {
  const failed = status === "failed";
  const currentIdx = PIPELINE_STAGES.findIndex((s) => s.key === status);

  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STAGES.map((stage, i) => {
        const Icon = stage.icon;
        const done = !failed && i < currentIdx;
        const active = !failed && i === currentIdx;
        const isFailed = failed && i === currentIdx;

        return (
          <div key={stage.key} className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <motion.div
                  className={cn(
                    "flex items-center justify-center rounded-full transition-colors",
                    done && "bg-emerald-500/20 text-emerald-600",
                    active && stage.key === "completed" && "bg-emerald-500/20 text-emerald-600",
                    active && stage.key !== "completed" && "bg-primary/20 text-primary",
                    isFailed && "bg-red-500/20 text-red-600",
                    !done && !active && !isFailed && "bg-muted text-muted-foreground/40"
                  )}
                  style={{ width: 28, height: 28 }}
                  animate={active && stage.key !== "completed" ? { scale: [1, 1.15, 1] } : {}}
                  transition={active && stage.key !== "completed" ? { repeat: Infinity, duration: 1.5 } : {}}
                >
                  {active && !isFailed && stage.key !== "completed" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Icon className="h-3.5 w-3.5" />
                  )}
                </motion.div>
              </TooltipTrigger>
              <TooltipContent><span className="text-xs">{stage.label}</span></TooltipContent>
            </Tooltip>
            {i < PIPELINE_STAGES.length - 1 && (
              <div className={cn("h-0.5 w-4 rounded-full", done ? "bg-emerald-500/40" : "bg-border")} />
            )}
          </div>
        );
      })}
      {failed && (
        <span className="ml-2 text-[11px] text-red-600 font-medium">Failed</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Coverage Bar                                                       */
/* ------------------------------------------------------------------ */

export function CoverageBar({ value, max = 100, label, color = "bg-primary" }: {
  value: number;
  max?: number;
  label: string;
  color?: string;
}) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <motion.div
          className={cn("h-full rounded-full", color)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Chunk Card                                                         */
/* ------------------------------------------------------------------ */

export function ChunkCard({
  chunk,
  onApprove,
  onReject,
  onView,
  compact = false,
}: {
  chunk: KnowledgeChunk;
  onApprove?: () => void;
  onReject?: () => void;
  onView?: () => void;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="group"
    >
      <Card className="border-border/60 hover:border-primary/30 transition-colors">
        <CardContent className={cn("space-y-3", compact ? "p-3" : "p-4")}>
          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-1.5">
            <ModuleBadge module={chunk.module_number} />
            <BloomBadge level={chunk.bloom_level} />
            <COBadge co={chunk.co_mapping} />
            <ApprovalBadge status={chunk.approval_status} />
            <div className="ml-auto">
              <AIConfidenceBadge score={chunk.confidence_score} />
            </div>
          </div>

          {/* Topic */}
          {chunk.topic_name && (
            <p className="text-sm font-medium text-foreground leading-snug">{chunk.topic_name}</p>
          )}

          {/* Text preview */}
          <p className={cn("text-sm text-muted-foreground leading-relaxed", compact ? "line-clamp-2" : "line-clamp-4")}>
            {chunk.chunk_text}
          </p>

          {/* Footer */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-[11px] text-muted-foreground/60">
              {chunk.token_count} tokens · Chunk #{chunk.chunk_index + 1}
              {chunk.page_number != null && ` · p.${chunk.page_number}`}
            </span>
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {onView && (
                <button onClick={onView} className="p-1 rounded hover:bg-muted" title="View">
                  <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              )}
              {onApprove && chunk.approval_status === "pending_review" && (
                <button onClick={onApprove} className="p-1 rounded hover:bg-emerald-500/10" title="Approve">
                  <ThumbsUp className="h-3.5 w-3.5 text-emerald-600" />
                </button>
              )}
              {onReject && chunk.approval_status === "pending_review" && (
                <button onClick={onReject} className="p-1 rounded hover:bg-red-500/10" title="Reject">
                  <ThumbsDown className="h-3.5 w-3.5 text-red-600" />
                </button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Metric Card (for dashboard)                                        */
/* ------------------------------------------------------------------ */

export function MetricCard({ title, value, subtitle, icon: Icon, trend, color = "text-primary" }: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: typeof FileText;
  trend?: { value: number; label: string };
  color?: string;
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="border-border/60">
        <CardContent className="p-5">
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{title}</p>
              <p className="text-2xl font-bold tabular-nums text-foreground">{value}</p>
              {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
            </div>
            <div className={cn("rounded-lg bg-muted p-2.5", color)}>
              <Icon className="h-5 w-5" />
            </div>
          </div>
          {trend && (
            <div className="mt-3 flex items-center gap-1 text-xs">
              <Zap className="h-3 w-3 text-emerald-500" />
              <span className="text-emerald-600 font-medium">+{trend.value}%</span>
              <span className="text-muted-foreground">{trend.label}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty state                                                        */
/* ------------------------------------------------------------------ */

export function AcademicEmptyState({ title, description, icon: Icon = BookOpen, action }: {
  title: string;
  description: string;
  icon?: typeof BookOpen;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="rounded-2xl bg-muted/50 p-4 mb-4">
        <Icon className="h-10 w-10 text-muted-foreground/50" />
      </div>
      <h3 className="text-lg font-semibold text-foreground">{title}</h3>
      <p className="text-sm text-muted-foreground mt-1 max-w-md">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
