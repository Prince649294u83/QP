/**
 * Analytics — Production-grade academic analytics dashboard.
 *
 * Shows syllabus coverage, Bloom distribution, CO distribution,
 * question quality metrics, and module gap detection.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import {
  BarChart3,
  Brain,
  Target,
  BookOpen,
  Layers,
  TrendingUp,
  AlertTriangle,
  CheckCircle2,
  PieChart,
  FileText,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { CoverageBar, MetricCard, AcademicEmptyState } from "@/components/academic";
import { useTopicCoverage } from "@/lib/academic-api";
import { useSubjects, useQuestionBankSummary } from "@/lib/ai-api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Cell,
  RadialBarChart,
  RadialBar,
  Legend,
  PieChart as RechartsPie,
  Pie,
} from "recharts";

const BLOOM_COLORS: Record<string, string> = {
  L1: "#38bdf8", L2: "#3b82f6", L3: "#8b5cf6",
  L4: "#f59e0b", L5: "#f97316", L6: "#ef4444",
};

const CO_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ef4444"];

export default function Analytics() {
  const { data: subjects } = useSubjects();
  const [subjectId, setSubjectId] = useState<number | undefined>();
  const { data: summary } = useQuestionBankSummary(subjectId);
  const { data: coverage } = useTopicCoverage(subjectId ?? 0);

  const totalQuestions = summary?.total_questions ?? 0;
  const totalChunks = coverage?.total_chunks ?? 0;
  const totalDocs = coverage?.total_documents ?? 0;

  // Bloom chart data
  const bloomData = Object.entries(summary?.by_rbt ?? {}).map(([level, count]) => ({
    name: level,
    value: count as number,
    fill: BLOOM_COLORS[level] ?? "#94a3b8",
  }));

  // CO chart data
  const coData = Object.entries(summary?.by_co ?? {}).map(([co, count], i) => ({
    name: co,
    value: count as number,
    fill: CO_COLORS[i % CO_COLORS.length],
  }));

  // Module coverage data
  const moduleData = [1, 2, 3, 4, 5].map((m) => {
    const byModule = summary?.by_module ?? {};
    const count = byModule[`Module ${m}`] ?? byModule[String(m)] ?? 0;
    return { name: `M${m}`, value: count as number };
  });

  // Difficulty data
  const diffData = Object.entries(summary?.by_difficulty ?? {}).map(([diff, count]) => ({
    name: diff,
    value: count as number,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Analytics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Comprehensive academic coverage and quality metrics
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
              <SelectItem key={s.id} value={s.id.toString()}>{s.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Top Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard title="Total Questions" value={totalQuestions} icon={FileText} color="text-blue-600" />
        <MetricCard title="Knowledge Chunks" value={totalChunks} icon={Layers} color="text-violet-600" />
        <MetricCard title="Documents" value={totalDocs} icon={BookOpen} color="text-emerald-600" />
        <MetricCard
          title="Coverage Gaps"
          value={coverage?.gaps?.length ?? 0}
          icon={AlertTriangle}
          color={coverage?.gaps?.length ? "text-amber-600" : "text-emerald-600"}
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid md:grid-cols-2 gap-5">
        {/* Bloom Distribution */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Brain className="h-4 w-4 text-primary" />
                Bloom's Taxonomy Distribution
              </CardTitle>
            </CardHeader>
            <CardContent>
              {bloomData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={bloomData} barSize={36}>
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                    <RechartsTooltip
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e2e8f0" }}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {bloomData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                  No Bloom data available
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        {/* CO Distribution */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Target className="h-4 w-4 text-primary" />
                Course Outcome Distribution
              </CardTitle>
            </CardHeader>
            <CardContent>
              {coData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <RechartsPie>
                    <Pie
                      data={coData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={3}
                      dataKey="value"
                      label={({ name, value }) => `${name}: ${value}`}
                    >
                      {coData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                    <RechartsTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  </RechartsPie>
                </ResponsiveContainer>
              ) : (
                <div className="h-[260px] flex items-center justify-center text-sm text-muted-foreground">
                  No CO data available
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid md:grid-cols-2 gap-5">
        {/* Module Coverage */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-primary" />
                Module Coverage
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {moduleData.map((m) => {
                const maxVal = Math.max(1, ...moduleData.map((d) => d.value));
                return (
                  <CoverageBar
                    key={m.name}
                    label={m.name}
                    value={m.value}
                    max={maxVal}
                    color={m.value === 0 ? "bg-red-400" : m.value < maxVal * 0.3 ? "bg-amber-500" : "bg-emerald-500"}
                  />
                );
              })}
            </CardContent>
          </Card>
        </motion.div>

        {/* Coverage Gaps */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                Coverage Gaps & Alerts
              </CardTitle>
            </CardHeader>
            <CardContent>
              {coverage?.gaps?.length ? (
                <div className="space-y-2.5 max-h-[280px] overflow-y-auto pr-1">
                  {coverage.gaps.map((gap, i) => (
                    <div key={i} className="flex items-start gap-2.5 rounded-lg bg-amber-500/5 border border-amber-500/15 p-3">
                      <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                      <p className="text-sm text-foreground">{gap}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-10">
                  <CheckCircle2 className="h-10 w-10 text-emerald-500 mb-3" />
                  <p className="text-sm font-medium text-foreground">No gaps detected</p>
                  <p className="text-xs text-muted-foreground mt-1">All modules have sufficient coverage</p>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Topic Detail Table */}
      {coverage?.coverage?.length ? (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Layers className="h-4 w-4 text-primary" />
                Topic Coverage Detail
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/40">
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Module</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Topic</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Chunks</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Documents</th>
                      <th className="text-right py-2 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coverage.coverage.map((item, i) => (
                      <tr key={i} className="border-b border-border/20 hover:bg-muted/30 transition-colors">
                        <td className="py-2.5 px-3">
                          <Badge variant="outline" className="text-[10px]">M{item.module_number}</Badge>
                        </td>
                        <td className="py-2.5 px-3 font-medium">{item.topic_name}</td>
                        <td className="py-2.5 px-3 text-right tabular-nums">{item.chunk_count}</td>
                        <td className="py-2.5 px-3 text-right tabular-nums">{item.document_count}</td>
                        <td className="py-2.5 px-3 text-right">
                          <span className={cn(
                            "text-xs font-medium tabular-nums",
                            item.avg_confidence >= 0.7 ? "text-emerald-600" : item.avg_confidence >= 0.4 ? "text-amber-600" : "text-red-600"
                          )}>
                            {(item.avg_confidence * 100).toFixed(0)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      ) : null}
    </div>
  );
}
