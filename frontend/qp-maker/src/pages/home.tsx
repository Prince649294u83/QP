/**
 * Dashboard — Role-aware academic command center.
 */
import { motion } from "framer-motion";
import { Link } from "wouter";
import {
  ArrowRight,
  BookOpen,
  Brain,
  CheckCircle2,
  FileText,
  Layers,
  Sparkles,
  Upload,
  AlertTriangle,
  BarChart3,
  Clock,
  TrendingUp,
  Target,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { MetricCard, CoverageBar, AIConfidenceBadge } from "@/components/academic";
import { useSubjects, useQuestionBankSummary } from "@/lib/ai-api";
import { useAcademicDocuments, useTopicCoverage } from "@/lib/academic-api";

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.35 },
};

export default function Dashboard() {
  const { data: subjects } = useSubjects();
  const { data: summary } = useQuestionBankSummary();
  const { data: docs } = useAcademicDocuments();

  const totalDocs = docs?.total ?? 0;
  const totalQuestions = summary?.total_questions ?? 0;
  const verifiedQuestions = summary?.verified_questions ?? 0;
  const pendingQuestions = summary?.pending_questions ?? 0;

  return (
    <div className="space-y-7">
      {/* ---- Welcome Banner ---- */}
      <motion.section {...fadeUp} className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary/90 via-primary to-primary/80 text-primary-foreground shadow-lg">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(255,255,255,0.15)_0%,_transparent_60%)]" />
        <div className="relative z-10 p-7 md:p-9 flex flex-col md:flex-row items-start md:items-center gap-6">
          <div className="flex-1 space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-xs font-medium">
              <ShieldCheck className="h-3.5 w-3.5" />
              DSATM Academic Portal
            </div>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight">Welcome back, Faculty</h1>
            <p className="text-sm text-primary-foreground/70 max-w-lg leading-relaxed">
              Your AI-powered academic workspace is ready. Upload materials, generate VTU-compliant papers, and track syllabus coverage — all in one place.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/upload">
              <Button size="sm" variant="secondary" className="font-semibold shadow-md">
                <Upload className="h-4 w-4 mr-2" />
                Upload Materials
              </Button>
            </Link>
            <Link href="/generate">
              <Button size="sm" className="bg-white/15 text-white border border-white/20 hover:bg-white/25 font-semibold">
                <Sparkles className="h-4 w-4 mr-2" />
                Generate Paper
              </Button>
            </Link>
          </div>
        </div>
      </motion.section>

      {/* ---- Metric Cards ---- */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Documents"
          value={totalDocs}
          subtitle="Uploaded materials"
          icon={FileText}
          color="text-blue-600"
        />
        <MetricCard
          title="Knowledge Chunks"
          value={summary?.retrieval_ready_questions ?? 0}
          subtitle="Retrieval-ready"
          icon={Layers}
          color="text-violet-600"
        />
        <MetricCard
          title="Questions"
          value={totalQuestions}
          subtitle={`${verifiedQuestions} verified`}
          icon={Brain}
          color="text-emerald-600"
        />
        <MetricCard
          title="Subjects"
          value={subjects?.length ?? 0}
          subtitle="Active subjects"
          icon={BookOpen}
          color="text-amber-600"
        />
      </div>

      {/* ---- Two Column Layout ---- */}
      <div className="grid md:grid-cols-5 gap-5">
        {/* Left — Quick Actions & Coverage */}
        <div className="md:col-span-3 space-y-5">
          {/* Quick Actions */}
          <motion.div {...fadeUp}>
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Quick Actions
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                  {[
                    { href: "/upload", icon: Upload, label: "Upload Notes", desc: "PDF, PPT, DOCX", color: "bg-blue-500/10 text-blue-600" },
                    { href: "/generate", icon: Sparkles, label: "Generate Paper", desc: "AI-powered", color: "bg-violet-500/10 text-violet-600" },
                    { href: "/knowledge", icon: BookOpen, label: "Knowledge Base", desc: "Browse chunks", color: "bg-emerald-500/10 text-emerald-600" },
                    { href: "/questions", icon: FileText, label: "Question Bank", desc: "Manage questions", color: "bg-amber-500/10 text-amber-600" },
                    { href: "/review", icon: ShieldCheck, label: "Review Center", desc: "Pending approvals", color: "bg-rose-500/10 text-rose-600" },
                    { href: "/analytics", icon: BarChart3, label: "Analytics", desc: "Coverage stats", color: "bg-teal-500/10 text-teal-600" },
                  ].map((action) => (
                    <Link key={action.href} href={action.href}>
                      <div className="group flex items-center gap-3 rounded-xl border border-border/50 p-3.5 hover:border-primary/30 hover:bg-muted/50 transition-all cursor-pointer">
                        <div className={`rounded-lg p-2 ${action.color}`}>
                          <action.icon className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground truncate">{action.label}</p>
                          <p className="text-[11px] text-muted-foreground">{action.desc}</p>
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              </CardContent>
            </Card>
          </motion.div>

          {/* Module Coverage */}
          <motion.div {...fadeUp}>
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <Target className="h-4 w-4 text-primary" />
                    Syllabus Coverage
                  </CardTitle>
                  <Link href="/analytics">
                    <span className="text-xs text-primary font-medium cursor-pointer hover:underline flex items-center gap-1">
                      View Details <ArrowRight className="h-3 w-3" />
                    </span>
                  </Link>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {[1, 2, 3, 4, 5].map((m) => {
                  const byModule = summary?.by_module ?? {};
                  const count = byModule[`Module ${m}`] ?? byModule[String(m)] ?? 0;
                  const maxPerModule = Math.max(1, ...Object.values(byModule).map(Number));
                  return (
                    <CoverageBar
                      key={m}
                      label={`Module ${m}`}
                      value={count}
                      max={maxPerModule}
                      color={count === 0 ? "bg-red-400" : count < maxPerModule * 0.3 ? "bg-amber-500" : "bg-emerald-500"}
                    />
                  );
                })}
              </CardContent>
            </Card>
          </motion.div>
        </div>

        {/* Right — Activity Feed & Gaps */}
        <div className="md:col-span-2 space-y-5">
          {/* Recent Uploads */}
          <motion.div {...fadeUp}>
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Clock className="h-4 w-4 text-primary" />
                  Recent Activity
                </CardTitle>
              </CardHeader>
              <CardContent>
                {summary?.recent_documents?.length ? (
                  <div className="space-y-3">
                    {summary.recent_documents.slice(0, 5).map((doc) => (
                      <div key={doc.id} className="flex items-start gap-3">
                        <div className="mt-0.5 h-8 w-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                          <FileText className="h-4 w-4 text-muted-foreground" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-foreground truncate">{doc.filename}</p>
                          <p className="text-[11px] text-muted-foreground">
                            {doc.question_count} questions · {doc.upload_status}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No recent uploads. Start by uploading academic materials.
                  </p>
                )}
              </CardContent>
            </Card>
          </motion.div>

          {/* Coverage Gaps */}
          <motion.div {...fadeUp}>
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  Coverage Alerts
                </CardTitle>
              </CardHeader>
              <CardContent>
                {summary?.gaps?.length ? (
                  <div className="space-y-2">
                    {summary.gaps.slice(0, 5).map((gap, i) => (
                      <div key={i} className="flex items-start gap-2 text-sm">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
                        <span className="text-muted-foreground">{gap}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <CheckCircle2 className="h-8 w-8 text-emerald-500 mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">No gaps detected. Good coverage!</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>

          {/* Bloom Distribution */}
          <motion.div {...fadeUp}>
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Brain className="h-4 w-4 text-primary" />
                  Bloom Distribution
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {["L1", "L2", "L3", "L4", "L5", "L6"].map((level) => {
                  const count = summary?.by_rbt?.[level] ?? 0;
                  const total = totalQuestions || 1;
                  const colors: Record<string, string> = {
                    L1: "bg-sky-500", L2: "bg-blue-500", L3: "bg-violet-500",
                    L4: "bg-amber-500", L5: "bg-orange-500", L6: "bg-rose-500",
                  };
                  return (
                    <CoverageBar
                      key={level}
                      label={level}
                      value={count}
                      max={total}
                      color={colors[level] ?? "bg-primary"}
                    />
                  );
                })}
              </CardContent>
            </Card>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
