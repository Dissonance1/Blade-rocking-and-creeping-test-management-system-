import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
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
} from "lucide-react";
import { format, parseISO, subDays } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { reportService } from "@/services/reportService";
import { extractApiError } from "@/services/api";
import type { BladeStatus, Report, ReportStatus } from "@/types";
import { cn } from "@/utils/cn";

// ─── Schema ───────────────────────────────────────────────────────────────────

const reportSchema = z.object({
  report_type: z.enum(["PDF", "EXCEL"]),
  date_from: z.string().min(1, "Start date required"),
  date_to: z.string().min(1, "End date required"),
  statuses: z.array(z.string()).default([]),
  include_rejected: z.boolean().default(false),
});

type ReportFormValues = z.infer<typeof reportSchema>;

// ─── Status options ───────────────────────────────────────────────────────────

const ALL_STATUSES: { value: BladeStatus; label: string }[] = [
  { value: "CREATED", label: "Created" },
  { value: "OH_INSPECTION", label: "OH Inspection" },
  { value: "MEASUREMENTS_RECORDED", label: "Measurements Recorded" },
  { value: "SENT_TO_ASSEMBLY", label: "Sent to Assembly" },
  { value: "SLOT_ASSIGNED", label: "Slot Assigned" },
  { value: "BALANCING_IN_PROGRESS", label: "Balancing In Progress" },
  { value: "BALANCING_COMPLETED", label: "Balancing Completed" },
  { value: "COMPLETED", label: "Completed" },
  { value: "REJECTED", label: "Rejected" },
];

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

  const {
    register,
    handleSubmit,
    control,
    watch,
    formState: { errors },
  } = useForm<ReportFormValues>({
    resolver: zodResolver(reportSchema),
    defaultValues: {
      report_type: "PDF",
      date_from: format(subDays(new Date(), 30), "yyyy-MM-dd"),
      date_to: format(new Date(), "yyyy-MM-dd"),
      statuses: [],
      include_rejected: false,
    },
  });

  const selectedStatuses = watch("statuses");
  const reportType = watch("report_type");

  const generateMutation = useMutation({
    mutationFn: (values: ReportFormValues) =>
      reportService.generate({
        name: `${values.report_type} Report`,
        report_type: values.report_type,
        filter_params: {
          date_from: values.date_from,
          date_to: values.date_to,
          status: values.statuses as BladeStatus[],
          include_rejected: values.include_rejected,
        },
      }),
    onSuccess: (_report) => {
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      setActiveTab("my-reports");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => reportService.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reports"] }),
  });

  const toggleStatus = (
    status: BladeStatus,
    currentValues: string[],
    onChange: (v: string[]) => void
  ) => {
    if (currentValues.includes(status)) {
      onChange(currentValues.filter((s) => s !== status));
    } else {
      onChange([...currentValues, status]);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="max-w-screen-lg mx-auto">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-orange-500" />
            Reports
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">Generate and download operational reports</p>
        </div>
      </div>

      <div className="max-w-screen-lg mx-auto px-6 py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 h-auto p-1 mb-6 rounded-xl shadow-sm">
            <TabsTrigger
              value="generate"
              className="rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              Generate Report
            </TabsTrigger>
            <TabsTrigger
              value="my-reports"
              className="rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              My Reports
              {reports.filter((r) => r.status === "GENERATING").length > 0 && (
                <span className="ml-2">
                  <Loader2 className="w-3 h-3 animate-spin text-amber-400 inline" />
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          {/* Generate tab */}
          <TabsContent value="generate">
            <form onSubmit={handleSubmit((v) => generateMutation.mutate(v))}>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left: form */}
                <div className="lg:col-span-2 space-y-5">
                  {/* Report type */}
                  <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">Report Format</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Controller
                        control={control}
                        name="report_type"
                        render={({ field }) => (
                          <div className="flex gap-3">
                            {(["PDF", "EXCEL"] as const).map((type) => (
                              <button
                                key={type}
                                type="button"
                                onClick={() => field.onChange(type)}
                                className={cn(
                                  "flex flex-1 items-center gap-3 rounded-xl border-2 px-4 py-3 transition-colors",
                                  field.value === type
                                    ? "border-orange-500 bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-300"
                                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600"
                                )}
                              >
                                {type === "PDF" ? (
                                  <FileText className="w-5 h-5" />
                                ) : (
                                  <FileSpreadsheet className="w-5 h-5" />
                                )}
                                <div className="text-left">
                                  <p className="font-semibold text-sm">{type}</p>
                                  <p className="text-xs opacity-70">
                                    {type === "PDF" ? "Printable report" : "Excel spreadsheet"}
                                  </p>
                                </div>
                              </button>
                            ))}
                          </div>
                        )}
                      />
                    </CardContent>
                  </Card>

                  {/* Date range */}
                  <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">Date Range</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                          <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">From</Label>
                          <Input
                            type="date"
                            className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                            {...register("date_from")}
                          />
                          {errors.date_from && (
                            <p className="text-red-500 dark:text-red-400 text-xs">{errors.date_from.message}</p>
                          )}
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">To</Label>
                          <Input
                            type="date"
                            className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                            {...register("date_to")}
                          />
                          {errors.date_to && (
                            <p className="text-red-500 dark:text-red-400 text-xs">{errors.date_to.message}</p>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Status filter */}
                  <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">
                        Status Filter{" "}
                        <span className="text-slate-400 dark:text-slate-500 font-normal text-xs ml-1">
                          (leave empty for all)
                        </span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Controller
                        control={control}
                        name="statuses"
                        render={({ field }) => (
                          <div className="grid grid-cols-2 gap-2">
                            {ALL_STATUSES.map((s) => (
                              <label
                                key={s.value}
                                className="flex items-center gap-2.5 cursor-pointer rounded-xl border border-slate-200 dark:border-slate-700/50 px-3 py-2 hover:border-slate-300 dark:hover:border-slate-600 transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/30"
                              >
                                <Checkbox
                                  checked={field.value.includes(s.value)}
                                  onCheckedChange={() =>
                                    toggleStatus(s.value, field.value, field.onChange)
                                  }
                                />
                                <span className="text-slate-700 dark:text-slate-300 text-sm">{s.label}</span>
                              </label>
                            ))}
                          </div>
                        )}
                      />
                    </CardContent>
                  </Card>
                </div>

                {/* Right: options + submit */}
                <div className="space-y-5">
                  <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-900 dark:text-white text-sm font-semibold">Options</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <Controller
                        control={control}
                        name="include_rejected"
                        render={({ field }) => (
                          <div className="flex items-center justify-between">
                            <Label className="text-slate-600 dark:text-slate-300 text-sm cursor-pointer">
                              Include Rejected Blades
                            </Label>
                            <Switch
                              checked={field.value}
                              onCheckedChange={field.onChange}
                            />
                          </div>
                        )}
                      />
                    </CardContent>
                  </Card>

                  {/* Summary preview */}
                  <Card className="bg-slate-800 dark:bg-slate-700/40 border border-slate-700 dark:border-slate-700/60 rounded-xl">
                    <CardContent className="p-4 space-y-2 text-sm">
                      <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">
                        Report Preview
                      </p>
                      <div className="flex items-center gap-2">
                        {reportType === "PDF" ? (
                          <FileText className="w-4 h-4 text-red-400" />
                        ) : (
                          <FileSpreadsheet className="w-4 h-4 text-green-400" />
                        )}
                        <span className="text-white font-medium">{reportType} Report</span>
                      </div>
                      <p className="text-slate-400 text-xs">
                        {selectedStatuses.length === 0
                          ? "All statuses"
                          : `${selectedStatuses.length} status(es) selected`}
                      </p>
                    </CardContent>
                  </Card>

                  {generateMutation.isError && (
                    <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                      <AlertCircle className="h-4 w-4 text-red-500" />
                      <AlertDescription className="text-red-700 dark:text-red-300">
                        {extractApiError(generateMutation.error)}
                      </AlertDescription>
                    </Alert>
                  )}

                  <Button
                    type="submit"
                    disabled={generateMutation.isPending}
                    className="w-full bg-orange-500 hover:bg-orange-600 text-white shadow-md shadow-orange-200 dark:shadow-orange-900/30"
                  >
                    {generateMutation.isPending ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Generating…
                      </>
                    ) : (
                      <>
                        <BarChart3 className="w-4 h-4" />
                        Generate Report
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </form>
          </TabsContent>

          {/* My reports tab */}
          <TabsContent value="my-reports">
            <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardHeader className="flex-row items-center justify-between pb-3">
                <CardTitle className="text-slate-900 dark:text-white text-base">My Reports</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
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
                    <p className="text-sm mt-1">Generate your first report above</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-800 dark:bg-slate-700">
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
                              rowIdx % 2 === 0 ? "bg-white dark:bg-slate-800/40" : "bg-slate-50 dark:bg-slate-800/20"
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
