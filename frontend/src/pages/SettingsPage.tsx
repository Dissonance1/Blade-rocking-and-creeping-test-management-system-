import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import {
  User as UserIcon,
  Lock,
  Bell,
  Check,
  Loader2,
  AlertCircle,
  Eye,
  EyeOff,
  Shield,
} from "lucide-react";
import { SettingsIcon } from "@/components/common/CustomIcons";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

import { useAuthStore } from "@/store/authStore";
import { authService } from "@/services/authService";

import api, { extractApiError } from "@/services/api";
import type { User } from "@/types";

// ─── Schemas ──────────────────────────────────────────────────────────────────

const profileSchema = z.object({
  full_name: z.string().min(2, "Full name must be at least 2 characters"),
});
type ProfileFormValues = z.infer<typeof profileSchema>;

const passwordSchema = z
  .object({
    old_password: z.string().min(1, "Current password is required"),
    new_password: z.string().min(8, "New password must be at least 8 characters"),
    confirm_password: z.string().min(1, "Please confirm your new password"),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  });
type PasswordFormValues = z.infer<typeof passwordSchema>;

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  id,
  icon,
  title,
  description,
  children,
  accentColor = "bg-orange-500",
}: {
  id?: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
  accentColor?: string;
}) {
  return (
    <Card id={id} className="bg-white dark:bg-background border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm scroll-mt-6">
      <CardHeader className="pb-4 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-700/50">
        <CardTitle className="text-slate-900 dark:text-white text-base flex items-center gap-2">
          <div className={`w-7 h-7 rounded-lg ${accentColor} flex items-center justify-center shrink-0`}>
            {icon}
          </div>
          {title}
        </CardTitle>
        <CardDescription className="text-slate-500 dark:text-slate-400">{description}</CardDescription>
      </CardHeader>
      <CardContent className="pt-4 px-4 sm:px-6">{children}</CardContent>
    </Card>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const hasRole = useAuthStore((s) => s.hasRole);
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash]);

  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState(false);

  // Notification preferences (local state — would be saved to backend in prod)
  const [notifPrefs, setNotifPrefs] = useState({
    status_changes: true,
    rejections: true,
    assignments: true,
    system: false,
  });

  // Profile form
  const {
    register: regProfile,
    handleSubmit: handleProfile,
    formState: { errors: profileErrors },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: { full_name: user?.full_name ?? "" },
  });

  const profileMutation = useMutation({
    mutationFn: async (values: ProfileFormValues) => {
      const { data } = await api.patch<User>("/auth/me/profile", values);
      return data;
    },
    onSuccess: (updated: User) => {
      setUser(updated);
      setProfileSuccess(true);
      setTimeout(() => setProfileSuccess(false), 3000);
    },
  });

  // Password form
  const {
    register: regPwd,
    handleSubmit: handlePwd,
    reset: resetPwd,
    formState: { errors: pwdErrors },
  } = useForm<PasswordFormValues>({ resolver: zodResolver(passwordSchema) });

  const passwordMutation = useMutation({
    mutationFn: (values: PasswordFormValues) =>
      authService.changePassword(values.old_password, values.new_password),
    onSuccess: () => {
      resetPwd();
      setPasswordSuccess(true);
      setTimeout(() => setPasswordSuccess(false), 3000);
    },
  });

  function initials(name: string) {
    return name
      .split(" ")
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase();
  }

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-gradient-to-br from-slate-50 via-white to-orange-50/50 dark:bg-background dark:from-background dark:via-background dark:to-background text-slate-900 dark:text-white">
      {/* Header */}
      <div className="shrink-0 bg-white/60 backdrop-blur-xl dark:bg-background px-4 sm:px-6 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between w-full gap-2">
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 dark:text-white truncate flex items-center gap-2">
              <SettingsIcon className="w-5 h-5 text-orange-500 shrink-0" />
              Settings
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 tracking-tight mt-0.5">Manage your account and preferences</p>
          </div>
        </div>
      </div>

      <div className="w-full max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
        {/* Profile section */}
        <Section
          id="profile"
          icon={<UserIcon className="w-3.5 h-3.5 text-white" />}
          title="Profile"
          description="Update your personal information"
          accentColor="bg-orange-500"
        >
          {/* Avatar + read-only info */}
          <div className="flex items-center gap-4 mb-6 pb-6 border-b border-slate-200 dark:border-slate-700">
            <Avatar className="w-14 h-14">
              <AvatarFallback className="bg-orange-500 text-white text-lg font-semibold">
                {user ? initials(user.full_name) : "?"}
              </AvatarFallback>
            </Avatar>
            <div>
              <p className="text-slate-900 dark:text-white font-semibold">{user?.full_name}</p>
              <p className="text-slate-500 dark:text-slate-400 text-sm">{user?.email}</p>
              <div className="flex flex-wrap gap-1 mt-1">
                {user?.roles.map((r) => (
                  <span
                    key={r}
                    className="inline-flex items-center rounded-full bg-slate-800 text-white px-2 py-0.5 text-xs font-medium"
                  >
                    {r.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <form
            onSubmit={handleProfile((v) => profileMutation.mutate(v))}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Full Name</Label>
              <Input
                className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                {...regProfile("full_name")}
              />
              {profileErrors.full_name && (
                <p className="text-red-500 dark:text-red-400 text-xs">{profileErrors.full_name.message}</p>
              )}
            </div>

            {/* Read-only fields */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-slate-500 dark:text-slate-400 text-sm">Email (read-only)</Label>
                <Input
                  value={user?.email ?? ""}
                  readOnly
                  className="bg-slate-100 dark:bg-background border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 cursor-not-allowed"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-slate-500 dark:text-slate-400 text-sm">Username (read-only)</Label>
                <Input
                  value={user?.username ?? ""}
                  readOnly
                  className="bg-slate-100 dark:bg-background border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 cursor-not-allowed"
                />
              </div>
            </div>

            {profileMutation.isError && (
              <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                <AlertCircle className="h-4 w-4 text-red-500" />
                <AlertDescription className="text-red-700 dark:text-red-300">
                  {extractApiError(profileMutation.error)}
                </AlertDescription>
              </Alert>
            )}

            <div className="flex items-center gap-3">
              <Button
                type="submit"
                disabled={profileMutation.isPending}
                className="bg-orange-500 hover:bg-orange-600 text-white"
              >
                {profileMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
                Save Profile
              </Button>
              {profileSuccess && (
                <span className="text-emerald-500 text-sm flex items-center gap-1">
                  <Check className="w-4 h-4" /> Saved!
                </span>
              )}
            </div>
          </form>
        </Section>

        {/* Security section */}
        <Section
          id="security"
          icon={<Lock className="w-3.5 h-3.5 text-white" />}
          title="Security"
          description="Change your account password"
          accentColor="bg-slate-800"
        >
          <form
            onSubmit={handlePwd((v) => passwordMutation.mutate(v))}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Current Password</Label>
              <div className="relative">
                <Input
                  type={showOld ? "text" : "password"}
                  placeholder="••••••••"
                  className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white pr-10 focus:border-orange-400"
                  {...regPwd("old_password")}
                />
                <button
                  type="button"
                  onClick={() => setShowOld((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                  tabIndex={-1}
                >
                  {showOld ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {pwdErrors.old_password && (
                <p className="text-red-500 dark:text-red-400 text-xs">{pwdErrors.old_password.message}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">New Password</Label>
                <div className="relative">
                  <Input
                    type={showNew ? "text" : "password"}
                    placeholder="••••••••"
                    className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white pr-10 focus:border-orange-400"
                    {...regPwd("new_password")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowNew((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                    tabIndex={-1}
                  >
                    {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {pwdErrors.new_password && (
                  <p className="text-red-500 dark:text-red-400 text-xs">{pwdErrors.new_password.message}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label className="text-slate-600 dark:text-slate-300 text-sm font-medium">Confirm New Password</Label>
                <Input
                  type="password"
                  placeholder="••••••••"
                  className="bg-slate-50 dark:bg-background border-slate-300 dark:border-slate-600 text-slate-900 dark:text-white focus:border-orange-400"
                  {...regPwd("confirm_password")}
                />
                {pwdErrors.confirm_password && (
                  <p className="text-red-500 dark:text-red-400 text-xs">{pwdErrors.confirm_password.message}</p>
                )}
              </div>
            </div>

            {passwordMutation.isError && (
              <Alert variant="destructive" className="border-red-500/50 bg-red-50 dark:bg-red-500/10">
                <AlertCircle className="h-4 w-4 text-red-500" />
                <AlertDescription className="text-red-700 dark:text-red-300">
                  {extractApiError(passwordMutation.error)}
                </AlertDescription>
              </Alert>
            )}

            <div className="flex items-center gap-3">
              <Button
                type="submit"
                disabled={passwordMutation.isPending}
                className="bg-slate-800 hover:bg-slate-700 text-white"
              >
                {passwordMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Lock className="w-4 h-4" />
                )}
                Update Password
              </Button>
              {passwordSuccess && (
                <span className="text-emerald-500 text-sm flex items-center gap-1">
                  <Check className="w-4 h-4" /> Password updated!
                </span>
              )}
            </div>
          </form>
        </Section>

        {/* Preferences section */}
        <Section
          icon={<Bell className="w-3.5 h-3.5 text-white" />}
          title="Notification Preferences"
          description="Choose which events you want to be notified about"
          accentColor="bg-blue-500"
        >
          <div className="space-y-4">
            {[
              {
                key: "status_changes" as const,
                label: "Status Changes",
                description: "When a blade moves to a new workflow status",
              },
              {
                key: "rejections" as const,
                label: "Rejections",
                description: "When a blade is rejected at any station",
              },
              {
                key: "assignments" as const,
                label: "Slot Assignments",
                description: "When a blade is assigned to an assembly slot",
              },
              {
                key: "system" as const,
                label: "System Alerts",
                description: "System maintenance and configuration changes",
              },
            ].map(({ key, label, description }) => (
              <div key={key} className="flex items-center justify-between py-2">
                <div>
                  <p className="text-slate-900 dark:text-white text-sm font-medium">{label}</p>
                  <p className="text-slate-500 dark:text-slate-400 text-xs mt-0.5">{description}</p>
                </div>
                <Switch
                  checked={notifPrefs[key]}
                  onCheckedChange={(v) =>
                    setNotifPrefs((prev) => ({ ...prev, [key]: v }))
                  }
                />
              </div>
            ))}
          </div>
        </Section>

        {/* SUPER_ADMIN section */}
        {hasRole("SUPER_ADMIN") && (
          <Section
            icon={<Shield className="w-3.5 h-3.5 text-white" />}
            title="System Configuration"
            description="Super Admin only — global workflow settings"
            accentColor="bg-red-500"
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between py-2">
                <div>
                  <p className="text-slate-900 dark:text-white text-sm font-medium">Workflow Lock</p>
                  <p className="text-slate-500 dark:text-slate-400 text-xs mt-0.5">
                    Prevent all workflow transitions (maintenance mode)
                  </p>
                </div>
                <Switch defaultChecked={false} />
              </div>

              <Separator className="bg-slate-200 dark:bg-slate-700/50" />

              <div className="flex items-center justify-between py-2">
                <div>
                  <p className="text-slate-900 dark:text-white text-sm font-medium">OCR Mismatch Auto-Hold</p>
                  <p className="text-slate-500 dark:text-slate-400 text-xs mt-0.5">
                    Automatically put blades on hold when OCR mismatch is detected
                  </p>
                </div>
                <Switch defaultChecked />
              </div>

              <Separator className="bg-slate-200 dark:bg-slate-700/50" />

              <div className="flex items-center justify-between py-2">
                <div>
                  <p className="text-slate-900 dark:text-white text-sm font-medium">Notify on Rejection</p>
                  <p className="text-slate-500 dark:text-slate-400 text-xs mt-0.5">
                    Send system-wide notification when any blade is rejected
                  </p>
                </div>
                <Switch defaultChecked />
              </div>
            </div>
          </Section>
        )}
      </div>

    </div>
  );
}
