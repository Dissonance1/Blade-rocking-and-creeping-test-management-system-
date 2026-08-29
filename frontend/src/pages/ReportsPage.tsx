import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  FileSpreadsheet,
  Download,
  Trash2,
  Loader2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  BarChart3,
  Search,
  Package,
} from "lucide-react";
import { NotepadIcon } from "@/components/common/CustomIcons";
import { format, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { reportService } from "@/services/reportService";
import { batchService, type BatchSummary } from "@/services/batchService";
import { extractApiError } from "@/services/api";
import type { Report, ReportStatus } from "@/types";
import { cn } from "@/utils/cn";

// ─── Report status badge ──────────────────────────────────────────────────────

function ReportStatusBadge({ status }: { status: ReportStatus }) {
  switch (status) {
    case "COMPLETED":
    case "READY":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500 px-2 py-0.5 text-xs font-semibold text-white">
          <CheckCircle2 className="w-3 h-3" /> Ready
        </span>
      );
    case "GENERATING":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500 px-2 py-0.5 text-xs font-semibold text-white">
          <Loader2 className="w-3 h-3 animate-spin" /> Generating
        </span>
      );
    case "FAILED":
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-500 px-2 py-0.5 text-xs font-semibold text-white">
          <XCircle className="w-3 h-3" /> Failed
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-500 px-2 py-0.5 text-xs font-semibold text-white">
          <Clock className="w-3 h-3" /> Pending
        </span>
      );
  }
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function BladeTypeBadge({ bladeType }: { bladeType: "LPTR" | "HPTR" | null }) {
  if (!bladeType) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        bladeType === "HPTR"
          ? "bg-purple-500/15 text-purple-600 dark:text-purple-300"
          : "bg-blue-500/15 text-blue-600 dark:text-blue-300"
      )}
    >
      {bladeType}
    </span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ReportsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("generate");

  const { data: reportsData, isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => reportService.list({ limit: 100 }),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const hasGenerating = items.some(
        (r) => r.status === "GENERATING" || r.status === "PENDING"
      );
      return hasGenerating ? 3000 : false;
    },
  });
  const reports: Report[] = reportsData?.items ?? [];

  const deleteMutation = useMutation({
    mutationFn: (id: string) => reportService.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reports"] }),
  });

  // ─── Batch report state ────────────────────────────────────────────────────

  const [searchTerm, setSearchTerm] = useState("");
  const [selectedWorkOrder, setSelectedWorkOrder] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<"excel" | "pdf">("excel");

  const { data: batches = [], isLoading: batchesLoading } = useQuery({
    queryKey: ["batches-for-report"],
    queryFn: () => batchService.list(),
  });

  const filteredBatches = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return batches;
    return batches.filter(
      (b: BatchSummary) =>
        b.work_order_number.toLowerCase().includes(term) ||
        (b.part_number ?? "").toLowerCase().includes(term)
    );
  }, [batches, searchTerm]);

  const selectedBatch = batches.find((b) => b.work_order_number === selectedWorkOrder) ?? null;

  const exportMutation = useMutation({
    mutationFn: () => {
      if (!selectedWorkOrder) throw new Error("Select a batch first");
      return reportService.exportBatchReport(selectedWorkOrder, exportFormat);
    },
  });

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5 shadow-sm border-b border-slate-200 dark:border-slate-700/60">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <NotepadIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Reports
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">Generate and download operational reports</p>
          </div>
        </div>
      </div>

      <div className="w-full px-4 sm:px-6 py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 mb-6">
            <TabsList className="w-max min-w-full sm:w-auto flex-nowrap bg-white dark:bg-background border border-slate-200 dark:border-slate-700 h-auto p-1 rounded-xl shadow-sm">
              <TabsTrigger
                value="generate"
                className="shrink-0 rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                Batch Report
              </TabsTrigger>
              <TabsTrigger
                value="my-reports"
                className="shrink-0 rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                My Reports
                {reports.filter((r) => r.status === "GENERATING").length > 0 && (
                  <span className="ml-2">
                    <Loader2 className="w-3 h-3 animate-spin text-amber-400 inline" />
                  </span>
                )}
              </TabsTrigger>
            </TabsList>
          </div>

          {/* Batch Report tab */}
          <TabsContent value="generate">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left: search + batch list */}
              <div className="lg:col-span-2 space-y-5">
                <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                  <CardHeader className="pb-3 px-4 sm:px-6">
                    <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">
                      Select Batch (Work Order)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-4 sm:px-6 space-y-3">
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                      <Input
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        placeholder="Search by work order or part number…"
                        className="pl-9 bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                      />
                    </div>

                    <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-700/60 divide-y divide-slate-200 dark:divide-slate-700/50">
                      {batchesLoading ? (
                        <div className="flex items-center justify-center py-12 text-slate-400 dark:text-slate-500">
                          <Loader2 className="w-5 h-5 animate-spin mr-2" />
                          Loading batches…
                        </div>
                      ) : filteredBatches.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-slate-500">
                          <Package className="w-10 h-10 mb-2 opacity-20" />
                          <p className="text-sm font-medium">No batches match your search</p>
                        </div>
                      ) : (
                        filteredBatches.map((batch) => (
                          <button
                            key={batch.work_order_number}
                            type="button"
                            onClick={() => setSelectedWorkOrder(batch.work_order_number)}
                            className={cn(
                              "w-full text-left px-4 py-3 flex items-center justify-between gap-3 transition-colors",
                              selectedWorkOrder === batch.work_order_number
                                ? "bg-orange-50 dark:bg-orange-500/10"
                                : "hover:bg-slate-50 dark:hover:bg-slate-700/30"
                            )}
                          >
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-slate-900 dark:text-white truncate">
                                  {batch.work_order_number}
                                </span>
                                <BladeTypeBadge bladeType={batch.blade_type} />
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                                {batch.part_number ?? "—"}
                              </p>
                            </div>
                            <div className="shrink-0 text-right">
                              <p className="text-xs text-slate-500 dark:text-slate-400">
                                {batch.rows_complete_count}/{batch.blade_count} entered
                              </p>
                              <p className="text-xs text-slate-400 dark:text-slate-500">
                                {batch.current_status_label}
                              </p>
                            </div>
                          </button>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Right: format + preview + submit */}
              <div className="space-y-5">
                <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                  <CardHeader className="pb-3 px-4 sm:px-6">
                    <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">Report Format</CardTitle>
                  </CardHeader>
                  <CardContent className="px-4 sm:px-6">
                    <div className="flex flex-col gap-3">
                      {(["excel", "pdf"] as const).map((type) => (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setExportFormat(type)}
                          className={cn(
                            "flex items-center gap-3 rounded-xl border-2 px-4 py-3 transition-colors",
                            exportFormat === type
                              ? "border-orange-500 bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-300"
                              : "border-slate-200 dark:border-slate-700 bg-white dark:bg-background text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600"
                          )}
                        >
                          {type === "pdf" ? (
                            <FileText className="w-5 h-5" />
                          ) : (
                            <FileSpreadsheet className="w-5 h-5" />
                          )}
                          <div className="text-left">
                            <p className="font-semibold text-sm">{type === "pdf" ? "PDF" : "Excel"}</p>
                            <p className="text-xs opacity-70">
                              {type === "pdf" ? "Printable report" : "Excel spreadsheet"}
                            </p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                {/* Selected batch preview */}
                <Card className="bg-slate-800 dark:bg-background border border-slate-700 dark:border-slate-700/60 rounded-xl">
                  <CardContent className="p-4 space-y-2 text-sm">
                    <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">
                      Report Preview
                    </p>
                    {selectedBatch ? (
                      <>
                        <div className="flex items-center gap-2">
                          <span className="text-white font-medium">{selectedBatch.work_order_number}</span>
                          <BladeTypeBadge bladeType={selectedBatch.blade_type} />
                        </div>
                        <p className="text-slate-400 text-xs">
                          {selectedBatch.blade_count} blade(s) · Slot No., Serial No., Melt No., Weight,
                          Static Moment, Rocking
                          {selectedBatch.blade_type === "LPTR" ? ", Creep" : ""}
                        </p>
                      </>
                    ) : (
                      <p className="text-slate-400 text-xs">Select a batch on the left to preview.</p>
                    )}
                  </CardContent>
                </Card>

                {exportMutation.isError && (
                  <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                    <AlertCircle className="h-4 w-4 text-red-500" />
                    <AlertDescription className="text-red-700 dark:text-red-300">
                      {extractApiError(exportMutation.error)}
                    </AlertDescription>
                  </Alert>
                )}

                <Button
                  type="button"
                  disabled={!selectedWorkOrder || exportMutation.isPending}
                  onClick={() => exportMutation.mutate()}
                  className="w-full bg-orange-500 hover:bg-orange-600 text-white shadow-md shadow-orange-200 dark:shadow-orange-900/30"
                >
                  {exportMutation.isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Generating…
                    </>
                  ) : (
                    <>
                      <BarChart3 className="w-4 h-4" />
                      Generate &amp; Download
                    </>
                  )}
                </Button>
              </div>
            </div>
          </TabsContent>

          {/* My reports tab */}
          <TabsContent value="my-reports">
            <Card className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardHeader className="flex-row items-center justify-between pb-3 px-4 sm:px-6">
                <CardTitle className="text-slate-900 dark:text-white text-base">My Reports</CardTitle>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => queryClient.invalidateQueries({ queryKey: ["reports"] })}
                  className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                >
                  <RefreshCw className="w-4 h-4" />
                </Button>
              </CardHeader>
              <CardContent className="p-0">
                {isLoading ? (
                  <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                    <Loader2 className="w-6 h-6 animate-spin mr-2" />
                    Loading reports…
                  </div>
                ) : reports.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                    <BarChart3 className="w-12 h-12 mb-3 opacity-20" />
                    <p className="font-medium">No reports yet</p>
                    <p className="text-sm mt-1">Generate a batch report above</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm whitespace-nowrap">
                      <thead className="bg-slate-800 dark:bg-background">
                        <tr>
                          {["Name", "Type", "Status", "Created", "Size", "Actions"].map(
                            (h) => (
                              <th
                                key={h}
                                className={cn(
                                  "px-4 py-3 text-slate-100 font-semibold tracking-wide text-xs uppercase text-left",
                                  h === "Actions" && "text-right"
                                )}
                              >
                                {h}
                              </th>
                            )
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-200 dark:divide-slate-700/50">
                        {reports.map((report, rowIdx) => (
                          <tr
                            key={report.id}
                            className={cn(
                              "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
                              rowIdx % 2 === 0 ? "bg-white dark:bg-background" : "bg-slate-50 dark:bg-background"
                            )}
                          >
                            <td className="px-4 py-3 text-slate-900 dark:text-white font-medium">
                              {report.name || `Report #${report.id}`}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-1.5">
                                {report.report_type === "PDF" ? (
                                  <FileText className="w-4 h-4 text-red-500" />
                                ) : (
                                  <FileSpreadsheet className="w-4 h-4 text-emerald-500" />
                                )}
                                <span className="text-slate-700 dark:text-slate-300">{report.report_type}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <ReportStatusBadge status={report.status} />
                            </td>
                            <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                              {format(parseISO(report.created_at), "dd MMM yyyy HH:mm")}
                            </td>
                            <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                              {report.file_size_bytes
                                ? formatBytes(report.file_size_bytes)
                                : "—"}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-end gap-2">
                                {(report.status === "COMPLETED" || report.status === "READY") && (report.file_url ?? report.file_path) && (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => reportService.download(report.id, report.name)}
                                    className="border-2 border-emerald-400 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-600/20 h-8 text-xs gap-1"
                                  >
                                    <Download className="w-3 h-3" />
                                    Download
                                  </Button>
                                )}
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => deleteMutation.mutate(report.id)}
                                  disabled={deleteMutation.isPending}
                                  className="text-red-500 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-500/10 h-8 w-8 p-0"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </Button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>

    </div>
  );
}
