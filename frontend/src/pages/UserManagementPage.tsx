import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Plus,
  Pencil,
  Trash2,
  Lock,
  Unlock,
  Loader2,
  AlertCircle,
  Users,
  Search,
} from "lucide-react";
import { formatDistanceToNow, parseISO } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { userService } from "@/services/userService";
import api, { extractApiError } from "@/services/api";
import type { User, UserRole, Station } from "@/types";
import { cn } from "@/utils/cn";

// ─── Role config ──────────────────────────────────────────────────────────────

const ROLE_CFG: Record<UserRole, { label: string; color: string }> = {
  SUPER_ADMIN: { label: "Super Admin", color: "bg-red-500 text-white" },
  OH_OPERATOR: { label: "OH Operator", color: "bg-amber-500 text-white" },
  ASSEMBLY_OPERATOR: { label: "Assembly Operator", color: "bg-blue-500 text-white" },
  QA_VIEWER: { label: "QA Viewer", color: "bg-slate-500 text-white" },
};

function RoleBadge({ role }: { role: UserRole }) {
  const cfg = ROLE_CFG[role];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        cfg.color
      )}
    >
      {cfg.label}
    </span>
  );
}

function initials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

// ─── Create user schema ───────────────────────────────────────────────────────

const createSchema = z.object({
  full_name: z.string().min(2, "Full name required"),
  email: z.string().email("Invalid email"),
  username: z.string().min(3, "Username must be at least 3 characters"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  role: z.enum(["SUPER_ADMIN", "OH_OPERATOR", "ASSEMBLY_OPERATOR", "QA_VIEWER"] as const),
  station_id: z.string().optional(),
});
type CreateFormValues = z.infer<typeof createSchema>;

// ─── Edit user schema ─────────────────────────────────────────────────────────

const editSchema = z.object({
  full_name: z.string().min(2, "Full name required"),
  role: z.enum(["SUPER_ADMIN", "OH_OPERATOR", "ASSEMBLY_OPERATOR", "QA_VIEWER"] as const),
  station_id: z.string().optional(),
});
type EditFormValues = z.infer<typeof editSchema>;

// ─── Create user dialog ───────────────────────────────────────────────────────

function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { role: "OH_OPERATOR" },
  });

  const roleVal = watch("role");
  const stationVal = watch("station_id") ?? "";

  const { data: stations = [] } = useQuery<Station[]>({
    queryKey: ["stations"],
    queryFn: () => api.get<Station[]>("/stations/").then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (values: CreateFormValues) =>
      userService.create({
        full_name: values.full_name,
        email: values.email,
        username: values.username,
        password: values.password,
        roles: [values.role],
        // Send undefined (not empty string) when station_id is blank
        station_id: values.station_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      reset();
      onClose();
    },
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-slate-900 dark:text-white">Create New User</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit((v) => createMutation.mutate(v))}
          className="space-y-4 py-2"
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5 col-span-2">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Full Name</Label>
              <Input
                placeholder="John Smith"
                className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                {...register("full_name")}
              />
              {errors.full_name && (
                <p className="text-red-500 dark:text-red-400 text-xs">{errors.full_name.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Email</Label>
              <Input
                type="email"
                placeholder="john@company.com"
                className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                {...register("email")}
              />
              {errors.email && (
                <p className="text-red-500 dark:text-red-400 text-xs">{errors.email.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Username</Label>
              <Input
                placeholder="jsmith"
                className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                {...register("username")}
              />
              {errors.username && (
                <p className="text-red-500 dark:text-red-400 text-xs">{errors.username.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Password</Label>
              <Input
                type="password"
                placeholder="••••••••"
                className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                {...register("password")}
              />
              {errors.password && (
                <p className="text-red-500 dark:text-red-400 text-xs">{errors.password.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Role</Label>
              <Select
                value={roleVal}
                onValueChange={(v: UserRole) => setValue("role", v)}
              >
                <SelectTrigger className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
                  {(Object.keys(ROLE_CFG) as UserRole[]).map((r) => (
                    <SelectItem key={r} value={r} className="text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-slate-700">
                      {ROLE_CFG[r].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Station (optional)</Label>
              <Select
                value={stationVal || "__none__"}
                onValueChange={(v) => setValue("station_id", v === "__none__" ? "" : v)}
              >
                <SelectTrigger className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white">
                  <SelectValue placeholder="None" />
                </SelectTrigger>
                <SelectContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
                  <SelectItem value="__none__" className="text-slate-500 dark:text-slate-400">None</SelectItem>
                  {stations.map((s) => (
                    <SelectItem key={s.id} value={s.id} className="text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-slate-700">
                      {s.name} <span className="text-slate-400 text-xs ml-1">({s.code})</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {createMutation.isError && (
            <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <AlertDescription className="text-red-700 dark:text-red-300">
                {extractApiError(createMutation.error)}
              </AlertDescription>
            </Alert>
          )}

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createMutation.isPending}
              className="bg-orange-500 hover:bg-orange-600 text-white"
            >
              {createMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Plus className="w-4 h-4" />
              )}
              Create User
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Edit user dialog ─────────────────────────────────────────────────────────

function EditUserDialog({
  user,
  open,
  onClose,
}: {
  user: User | null;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const defaultEditValues = (u: User): EditFormValues => ({
    full_name: u.full_name,
    role: u.roles[0] ?? "QA_VIEWER",
    station_id: u.station_id ?? "",
  });

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
    defaultValues: user ? defaultEditValues(user) : { full_name: "", role: "QA_VIEWER" },
  });

  const roleVal = watch("role");
  const stationVal = watch("station_id") ?? "";

  const { data: stations = [] } = useQuery<Station[]>({
    queryKey: ["stations"],
    queryFn: () => api.get<Station[]>("/stations/").then((r) => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: async (values: EditFormValues) => {
      // Update basic profile fields
      await userService.update(user!.id, {
        full_name: values.full_name,
        station_id: values.station_id || undefined,
      });
      // Role change: remove old role, assign new one (if changed)
      const currentRole = user!.roles[0];
      if (currentRole && values.role !== currentRole) {
        try {
          await userService.removeRole(user!.id, currentRole);
        } catch { /* ignore if no existing role */ }
      }
      if (values.role) {
        await userService.assignRole(user!.id, values.role);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });

  if (!user) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="text-slate-900 dark:text-white">Edit User — {user.full_name}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit((v) => updateMutation.mutate(v))}
          className="space-y-4 py-2"
        >
          <div className="space-y-1.5">
            <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Full Name</Label>
            <Input
              className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
              {...register("full_name")}
            />
            {errors.full_name && (
              <p className="text-red-500 dark:text-red-400 text-xs">{errors.full_name.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Role</Label>
            <Select
              value={roleVal}
              onValueChange={(v: UserRole) => setValue("role", v)}
            >
              <SelectTrigger className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
                {(Object.keys(ROLE_CFG) as UserRole[]).map((r) => (
                  <SelectItem key={r} value={r} className="text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-slate-700">
                    {ROLE_CFG[r].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Station (optional)</Label>
            <Select
              value={stationVal || "__none__"}
              onValueChange={(v) => setValue("station_id", v === "__none__" ? "" : v)}
            >
              <SelectTrigger className="bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white">
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700">
                <SelectItem value="__none__" className="text-slate-500 dark:text-slate-400">None</SelectItem>
                {stations.map((s) => (
                  <SelectItem key={s.id} value={s.id} className="text-slate-900 dark:text-white hover:bg-slate-100 dark:hover:bg-slate-700">
                    {s.name} <span className="text-slate-400 text-xs ml-1">({s.code})</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {updateMutation.isError && (
            <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <AlertDescription className="text-red-700 dark:text-red-300">
                {extractApiError(updateMutation.error)}
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={updateMutation.isPending}
              className="bg-orange-500 hover:bg-orange-600 text-white"
            >
              {updateMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Pencil className="w-4 h-4" />
              )}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Tab config ───────────────────────────────────────────────────────────────

const ROLE_TABS: { value: UserRole | "ALL"; label: string }[] = [
  { value: "ALL", label: "All Users" },
  { value: "SUPER_ADMIN", label: "Super Admin" },
  { value: "OH_OPERATOR", label: "OH Operator" },
  { value: "ASSEMBLY_OPERATOR", label: "Assembly" },
  { value: "QA_VIEWER", label: "QA Viewer" },
];

// ─── Main component ───────────────────────────────────────────────────────────

export default function UserManagementPage() {
  const queryClient = useQueryClient();
  const [roleFilter, setRoleFilter] = useState<UserRole | "ALL">("ALL");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<User | null>(null);

  const { data: usersData, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => userService.list({ limit: 200 }),
  });
  const users: User[] = usersData?.items ?? [];

  const toggleActiveMutation = useMutation({
    mutationFn: (user: User) =>
      userService.update(user.id, { is_active: !user.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => userService.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setConfirmDelete(null);
    },
  });

  const filtered = users
    .filter((u) => roleFilter === "ALL" || u.roles.includes(roleFilter as UserRole))
    .filter(
      (u) =>
        !search ||
        u.full_name.toLowerCase().includes(search.toLowerCase()) ||
        u.email.toLowerCase().includes(search.toLowerCase())
    );

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 text-slate-900 dark:text-white">
      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 px-6 py-4 shadow-sm">
        <div className="flex items-center justify-between max-w-screen-xl mx-auto">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Users className="w-5 h-5 text-orange-500" />
              User Management
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">{users.length} total users</p>
          </div>
          <Button
            onClick={() => setShowCreate(true)}
            className="bg-orange-500 hover:bg-orange-600 text-white"
          >
            <Plus className="w-4 h-4" />
            Create User
          </Button>
        </div>
      </div>

      <div className="max-w-screen-xl mx-auto px-6 py-6 space-y-5">
        {/* Search */}
        <div className="flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
            <Input
              placeholder="Search by name or email…"
              value={search}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
              className="pl-9 bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-slate-500"
            />
          </div>
        </div>

        {/* Role tabs */}
        <Tabs
          value={roleFilter}
          onValueChange={(v: string) => setRoleFilter(v as UserRole | "ALL")}
        >
          <TabsList className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 h-auto p-1 rounded-xl shadow-sm">
            {ROLE_TABS.map((t) => (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="rounded-lg data-[state=active]:bg-orange-500 data-[state=active]:text-white text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value={roleFilter} className="mt-5">
            <Card className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm">
              <CardContent className="p-0">
                {isLoading ? (
                  <div className="flex items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                    <Loader2 className="w-6 h-6 animate-spin mr-2" />
                    Loading users…
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
                    <Users className="w-12 h-12 mb-3 opacity-20" />
                    <p className="font-medium">No users found</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-800 dark:bg-slate-700">
                        <tr>
                          {["User", "Role(s)", "Status", "Station", "Last Login", "Actions"].map(
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
                        {filtered.map((user, rowIdx) => (
                          <tr
                            key={user.id}
                            className={cn(
                              "transition-colors hover:bg-blue-50 dark:hover:bg-slate-700/30",
                              rowIdx % 2 === 0 ? "bg-white dark:bg-slate-800/40" : "bg-slate-50 dark:bg-slate-800/20"
                            )}
                          >
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-3">
                                <Avatar className="w-8 h-8">
                                  <AvatarFallback className="bg-orange-500 text-white text-xs font-semibold">
                                    {initials(user.full_name)}
                                  </AvatarFallback>
                                </Avatar>
                                <div>
                                  <p className="text-slate-900 dark:text-white font-medium">{user.full_name}</p>
                                  <p className="text-slate-500 dark:text-slate-400 text-xs">{user.email}</p>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1">
                                {user.roles.map((r) => (
                                  <RoleBadge key={r} role={r} />
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              {user.is_active ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500 text-white px-2 py-0.5 text-xs font-semibold">
                                  <span className="w-1.5 h-1.5 rounded-full bg-white" />
                                  Active
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 rounded-full bg-slate-400 text-white px-2 py-0.5 text-xs font-semibold">
                                  <span className="w-1.5 h-1.5 rounded-full bg-white/60" />
                                  Inactive
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                              {user.station_id ?? "—"}
                            </td>
                            <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                              {user.last_login
                                ? formatDistanceToNow(parseISO(user.last_login), {
                                    addSuffix: true,
                                  })
                                : "Never"}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setEditUser(user)}
                                  className="w-8 h-8 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                                  title="Edit"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => toggleActiveMutation.mutate(user)}
                                  disabled={toggleActiveMutation.isPending}
                                  className={cn(
                                    "w-8 h-8",
                                    user.is_active
                                      ? "text-amber-500 hover:text-amber-600"
                                      : "text-emerald-500 hover:text-emerald-600"
                                  )}
                                  title={user.is_active ? "Lock account" : "Unlock account"}
                                >
                                  {user.is_active ? (
                                    <Lock className="w-3.5 h-3.5" />
                                  ) : (
                                    <Unlock className="w-3.5 h-3.5" />
                                  )}
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setConfirmDelete(user)}
                                  className="w-8 h-8 text-red-500 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-500/10"
                                  title="Delete"
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

      <CreateUserDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <EditUserDialog user={editUser} open={!!editUser} onClose={() => setEditUser(null)} />

      {/* Delete confirmation */}
      <Dialog open={!!confirmDelete} onOpenChange={(v) => !v && setConfirmDelete(null)}>
        <DialogContent className="bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-900 dark:text-white">Delete User</DialogTitle>
          </DialogHeader>
          <p className="text-slate-700 dark:text-slate-300 text-sm py-2">
            Are you sure you want to permanently delete{" "}
            <span className="text-slate-900 dark:text-white font-semibold">{confirmDelete?.full_name}</span>? This
            action cannot be undone.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDelete(null)}
              className="border-2 border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              Cancel
            </Button>
            <Button
              onClick={() => confirmDelete && deleteMutation.mutate(confirmDelete.id)}
              disabled={deleteMutation.isPending}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
